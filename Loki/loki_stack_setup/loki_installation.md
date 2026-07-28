# Установка Loki в Kubernetes

## Определения

**Loki Helm-чарт** — пакет для развертывания Loki в Kubernetes. Начиная с версии 3.x, чарт поддерживает три основных режима: Single Binary, Simple Scalable и Distributed. Основной фокус в новых версиях сделан на производительности запросов и поддержке нативного поиска по Bloom-фильтрам.

**Важное замечание (март 2026):** Репозиторий `grafana https://grafana.github.io/helm-charts` переведен в режим обслуживания. Актуальный чарт Loki теперь находится в репозитории `grafana-community`.

```bash
helm repo add grafana-community https://grafana-community.github.io/helm-charts
helm repo update
```

**Текущая версия (апрель 2026):** Loki 3.x (стабильная), Helm-чарт 6.55.x+

**Подробнее:** [Обзор Grafana Loki](../loki_overview.md)

## Основные концепции

### Режимы развертывания

| Режим | Компоненты | Назначение |
| :--- | :--- | :--- |
| **Single Binary** | Все компоненты в одном поде | Тестирование, разработка, малые нагрузки |
| **Simple Scalable** | Разделение на чтение (Read), запись (Write) и системные задачи (Backend) | Рекомендуемый режим для Production средних и крупных масштабов |
| **Distributed** | Каждый микросервис (Ingester, Querier, Distributer и др.) запускается отдельно | Экстремальные нагрузки, требующие тонкой настройки каждого компонента |

### Архитектура Simple Scalable (рекомендуемый режим)

В этом режиме компоненты группируются по типам нагрузки. Gateway (обычно Nginx) выступает единой точкой входа, маршрутизируя трафик на Read или Write таргеты.

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

### Ключевые особенности Loki 3.x

1.  **Bloom Filters:** Позволяют значительно ускорить поиск по неиндексированным данным, отсекая чанки, которые точно не содержат искомый текст.
2.  **Structured Metadata:** Позволяет прикреплять метаданные к строкам логов без создания новых лейблов (и, следовательно, без увеличения кардинальности индекса).
3.  **TSDB Index:** Стандартный формат индекса, обеспечивающий высокую плотность хранения и скорость поиска.

## Практические сценарии

### Подготовка репозитория Helm

```bash
# Добавление актуального репозитория
helm repo add grafana-community https://grafana-community.github.io/helm-charts
helm repo update

# Получение стандартных значений для анализа
helm show values grafana-community/loki > loki_values.yaml
```

### Сценарий 1: Production — Simple Scalable с S3 и Bloom-фильтрами

Этот сценарий включает поддержку Bloom-фильтров для ускорения запросов и хранение данных в S3.

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
      endpoint: s3.amazonaws.com # Или ваш S3-совместимый эндпоинт
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

  # Включение Bloom-фильтров (Loki 3.0+)
  bloom_build_config:
    enabled: true
  bloom_gateway:
    enabled: true

  limits_config:
    retention_period: 744h  # 31 день
    max_query_series: 5000
    allow_structured_metadata: true # Включение структурированных метаданных

# Настройка компонентов Read (Querier, Frontend)
read:
  replicas: 3
  resources:
    requests:
      cpu: 1
      memory: 2Gi
    limits:
      cpu: 2
      memory: 4Gi

# Настройка компонентов Write (Ingester, Distributor)
write:
  replicas: 3
  resources:
    requests:
      cpu: 1
      memory: 2Gi
    limits:
      cpu: 2
      memory: 4Gi

# Настройка Backend (Compactor, Ruler)
backend:
  replicas: 2
  resources:
    requests:
      cpu: 500m
      memory: 1Gi

gateway:
  enabled: true
  replicas: 2
```

### Сценарий 2: Тестирование — Single Binary с локальным хранилищем

Подходит для небольших кластеров или сред разработки.

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

singleBinary:
  replicas: 1
  persistence:
    enabled: true
    size: 10Gi
  resources:
    requests:
      cpu: 500m
      memory: 1Gi

gateway:
  enabled: true
  replicas: 1
```

### Установка в кластер

```bash
# Создание namespace и установка
helm upgrade --install loki grafana-community/loki \
  --namespace logging \
  --create-namespace \
  -f loki_values.yaml \
  --wait --atomic
```

### Проверка работоспособности

```bash
# Просмотр статуса всех компонентов
kubectl get pods -n logging -l app.kubernetes.io/name=loki

# Проверка логов инжестера на наличие ошибок записи
kubectl logs -n logging -l app.kubernetes.io/component=write -f

# Проверка PVC при использовании локального хранилища
kubectl get pvc -n logging
```

### Диагностика типичных ошибок

| Ошибка | Возможная причина | Путь решения |
| :--- | :--- | :--- |
| **Pending Pods** | Недостаточно ресурсов или проблемы с PVC | Проверьте `kubectl describe pod` и наличие свободного места/прав на StorageClass |
| **Invalid Schema** | Неверная дата `from` или версия схемы | Дата `from` должна быть в прошлом. Для Loki 3.x используйте `v13` и `tsdb` |
| **S3 Connection Refused** | Неверный эндпоинт или сетевой доступ | Проверьте сетевые политики (NetworkPolicies) и валидность IAM-ключей |
| **403 Forbidden** | Недостаточно прав у ServiceAccount | Убедитесь, что у подов Loki есть права на запись в S3 бакет |

### Полезные команды для эксплуатации

```bash
# Просмотр текущей конфигурации в кластере
helm get values loki -n logging

# Список установленных версий чарта
helm history loki -n logging

# Быстрый откат при неудачном обновлении
helm rollback loki -n logging <version>
```

## Дополнительная информация

| Ресурс | Описание |
| :--- | :--- |
| [Обзор Loki](../loki_overview.md) | Архитектура, принципы работы и сравнение с ELK |
| [Установка Grafana](grafana_installation.md) | Настройка источника данных и дашбордов |
| [Примеры LogQL](logql_examples.md) | Практическое руководство по языку запросов |
| [Установка Alloy](alloy_installation.md) | Настройка современного агента сбора логов |
| [Документация по Bloom-фильтрам](https://grafana.com/docs/loki/latest/operations/bloom-filters/) | Детальная настройка ускорения запросов |
