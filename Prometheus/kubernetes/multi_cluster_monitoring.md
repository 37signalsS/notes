# Мультикластерный мониторинг Prometheus в Kubernetes

## Определения

**Мультикластерный мониторинг** — архитектурный паттерн, при котором метрики из нескольких Kubernetes-кластеров агрегируются в единое окно наблюдения (Global View) для централизованного алертинга, визуализации и анализа.

**Federation** — нативный протокол Prometheus для агрегации метрик между инстансами. Каждый кластер имеет локальный Prometheus, который отдает метрики через `/federate` эндпоинт.

**Thanos Sidecar** — компонент, добавляемый к каждому Prometheus через Operator, который выгружает закрытые TSDB-блоки в объектное хранилище (S3/GCS/MinIO) и предоставляет gRPC API для глобального запроса.

**Grafana Mimir** — микросервисная платформа для LTS, обеспечивающая горизонтальное масштабирование, мульти-тенантность и глобальный view через `remote_write` из каждого кластера.

> **См. также:** [Long-Term Storage](./operator/long_term_storage_integration.md) — Thanos/Mimir/VM, [High Availability](./operator/high_availability.md) — HA-паттерны.

## Основные концепции

### Три модели мультикластерного мониторинга

| Модель | Механизм | Плюсы | Минусы |
|:---|:---|:---|:---|
| **Federation** | HTTP `/federate` endpoint | Простота, нативный Prometheus | Ограничение 100M семплов/запрос, нет глобального индекса |
| **Thanos** | Sidecar + Object Storage + Query | Глобальный view, downsampling, long-term | Сложная архитектура, требует объектного хранилища |
| **Mimir** | `remote_write` + микросервисы | Масштабирование в миллиарды серий, multi-tenant | Зависимость от внешнего LTS, стоимость |

### Federation: когда использовать

- **< 3 кластеров**, < 100k активных серий на кластер.
- Не требуется долгосрочное хранение (только real-time view).
- Есть выделенный Prometheus "верхнего уровня" (Global Prometheus).

**Архитектура:**

```text
[ Cluster A Prometheus ]  [ Cluster B Prometheus ]
         |                          |
         | /federate                 | /federate
         v                          v
        [ Global Prometheus ]  <-- федерация
         |
         | alerting rules
         v
       [ Alertmanager ]
```

### Thanos: когда использовать

- **3+ кластеров**, долгосрочное хранение > 15 дней.
- Требуется downsampling (5m/1h) для истории.
- Есть объектное хранилище (S3, GCS, MinIO).

**Архитектура:**

```text
[ Cluster A ]                [ Cluster B ]
  Prometheus+Sidecar          Prometheus+Sidecar
       |                           |
       | objstore.upload            | objstore.upload
       v                           v
    [ S3 Bucket (common) ]  <-- общее хранилище
       |                           |
       v                           v
   [ Store Gateway ]          [ Store Gateway ]
       \                         /
        \                       /
         v                     v
        [ Thanos Query (Global View) ]
                  |
                  | PromQL
                  v
           [ Grafana / Alertmanager ]
```

### Mimir: когда использовать

- **> 5 кластеров** или > 10M активных серий.
- Требуется мульти-тенантность (разные команды/бизнес-единицы).
- Нужна горизонтальная масштабируемость LTS.

**Архитектура:**

```text
[ Cluster A ]  [ Cluster B ]  [ Cluster C ]
  Prometheus    Prometheus    Prometheus
       |              |              |
       | remote_write | remote_write |
       v              v              v
    [ Mimir Distributor / Ingester ]
                  |
                  v
           [ Object Storage ]
                  |
                  v
           [ Grafana (Global View) ]
```

---

## Практические сценарии

### Сценарий 1: Federation для 2 кластеров

**Кластер A (US-East):**

```yaml
apiVersion: monitoring.coreos.com/v1
kind: Prometheus
metadata:
  name: global
  namespace: monitoring
spec:
  replicas: 2
  serviceMonitorSelector: {}
  serviceMonitorNamespaceSelector: {}
  additionalScrapeConfigs:
    - job_name: federate-us-east
      honor_labels: true
      metrics_path: /federate
      params:
        'match[]':
          - '{job=~".+"}'
      static_configs:
        - targets:
            - prometheus-us-east.monitoring:9090
```

**Кластер B (EU-West) — аналогично с другим target.**

**Global Prometheus (US-East):**

```yaml
apiVersion: monitoring.coreos.com/v1
kind: Prometheus
metadata:
  name: global
  namespace: monitoring
spec:
  replicas: 1
  externalLabels:
    cluster: global
  additionalScrapeConfigs:
    - job_name: federate-us-east
      honor_labels: true
      metrics_path: /federate
      params:
        'match[]':
          - '{__name__=~".+"}'
      static_configs:
        - targets:
            - prometheus-us-east.monitoring:9090
    - job_name: federate-eu-west
      honor_labels: true
      metrics_path: /federate
      params:
        'match[]':
          - '{__name__=~".+"}'
      static_configs:
        - targets:
            - prometheus-eu-west.monitoring:9090
```

### Сценарий 2: Thanos через Prometheus Operator

```yaml
apiVersion: monitoring.coreos.com/v1
kind: Prometheus
metadata:
  name: main
  namespace: monitoring
spec:
  replicas: 2
  externalLabels:
    cluster: production-east
  thanos:
    image: quay.io/thanos/thanos:v0.41.0
    objectStorageConfig:
      key: thanos.yaml
      name: thanos-objstore-config
  retention: 15d
  resources:
    requests:
      memory: 4Gi
      cpu: 2
    limits:
      memory: 8Gi
---
apiVersion: v1
kind: Secret
metadata:
  name: thanos-objstore-config
  namespace: monitoring
stringData:
  thanos.yaml: |
    type: S3
    config:
      bucket: thanos-metrics
      endpoint: s3.us-east-1.amazonaws.com
      sse_config:
        type: SSE-S3
```

### Сценарий 3: Mimir через remote_write

**В каждом кластере:**

```yaml
apiVersion: monitoring.coreos.com/v1
kind: Prometheus
metadata:
  name: main
  namespace: monitoring
spec:
  replicas: 2
  externalLabels:
    cluster: production-east
  remoteWrite:
    - url: https://mimir.prod.internal/api/v1/push
      basicAuth:
        username:
          name: mimir-credentials
          key: username
        password:
          name: mimir-credentials
          key: password
      queueConfig:
        maxShards: 10
        capacity: 5000
        maxSamplesPerSend: 1000
        batchSendDeadline: 5s
        minBackoff: 30ms
        maxBackoff: 5s
      writeRelabelConfigs:
        - sourceLabels: [__name__]
          regex: 'go_.*'
          action: drop
```

### Сценарий 4: Алертинг в мультикластерной среде

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: multi-cluster-alerts
  namespace: monitoring
  labels:
    role: alert-rules
spec:
  groups:
    - name: multi-cluster
      rules:
        - alert: ClusterDown
          expr: |
            up{job=~".*"} == 0
            and on(cluster) count by (cluster) (up{job=~".*"} == 0) == count by (cluster) (up{job=~".*"})
          for: 5m
          labels:
            severity: critical
          annotations:
            summary: "Кластер {{ $labels.cluster }} полностью недоступен"

        - alert: HighLatencyCrossCluster
          expr: |
            histogram_quantile(0.99,
              sum(rate(http_request_duration_seconds_bucket{cluster!="us-east"}[5m])) by (le, service, cluster)
            ) > 1
          for: 10m
          labels:
            severity: warning
          annotations:
            summary: "Высокая латентность в кластере {{ $labels.cluster }}"
```

---

## Диагностика и устранение неисправностей

### Проблема: Federation не возвращает данные

**Причины:**

- `honor_labels: true` не установлен — метки кластера перезаписываются.
- Фильтр `match[]` слишком узкий.
- Prometheus "верхнего уровня" не имеет доступа к нижнему.

**Диагностика:**

```bash
# 1. Проверка federate endpoint
kubectl exec -n monitoring global-0 -- wget -qO- 'http://prometheus-us-east:9090/federate?match[]=%7B__name__%3D~%22up%22%7D' | head -20

# 2. Проверка логов Global Prometheus
kubectl logs -n monitoring global-0 -c prometheus | grep -i "federate\|error"

# 3. Проверка NetworkPolicy
kubectl get networkpolicy -n monitoring -o yaml | grep -A10 "federate\|prometheus"
```

### Проблема: Thanos Sidecar не загружает блоки

**Причины:**

- Неверный `thanos-objstore-config` Secret.
- Отсутствие доступа к S3/GCS/MinIO.
- Блоки не закрыты (прошло < 2 часов).

**Диагностика:**

```bash
# 1. Проверка логов sidecar
kubectl logs -n monitoring prometheus-main-0 -c thanos-sidecar | grep -E "upload|error|heartbeat"

# 2. Проверка метрик
kubectl exec -n monitoring prometheus-main-0 -c thanos-sidecar -- \
  wget -qO- 'http://localhost:10902/metrics' | grep thanos_shipper

# 3. Проверка доступа к хранилищу
kubectl exec -n monitoring prometheus-main-0 -c thanos-sidecar -- \
  thanos tools bucket ls --objstore.config-file=/etc/thanos/thanos.yaml
```

### Проблема: Дубликаты метрик в Global View

**Причины:**

- HA-пары в каждом кластере отправляют одни и те же метрики без дедупликации.
- `externalLabels` не содержат уникальный идентификатор реплики.

**Решение:**

```yaml
# В каждом кластере уникальные externalLabels
spec:
  externalLabels:
    cluster: production-east
    replica: $(POD_NAME)  # Operator подставит имя пода
```

### Частые ошибки на собеседованиях

1. **"Federation — лучший выбор для мультикластера"** — Нет. Federation имеет лимит 100M семплов на запрос и не подходит для кластеров с >500k серий. Для больших сред используйте Thanos или Mimir.

2. **"Thanos и Mimir — одно и то же"** — Нет. Thanos использует sidecar-паттерн и работает поверх существующего Prometheus. Mimir заменяет хранение через `remote_write` и требует отдельной инфраструктуры.

3. **"Дубликаты в HA — это проблема"** — Нет. Дубликаты — ожидаемое поведение HA-пары. Дедупликация происходит на уровне LTS (Thanos/Mimir) или Alertmanager (по `prometheus_replica`).

---

## Дополнительная информация

- [Long-Term Storage](./operator/long_term_storage_integration.md) — Thanos Sidecar, Mimir, VictoriaMetrics.
- [High Availability](./operator/high_availability.md) — HA-паттерны для Prometheus и Alertmanager.
- [Cost Optimization](./operator/cost_optimization.md) — оптимизация в мультикластерных средах.
- [GitOps Integration](./operator/gitops_integration.md) — ArgoCD ApplicationSet для multi-cluster.
- [Federation (Prometheus)](../scaling/federation.md) — нативная федерация.
- [Thanos Overview](../scaling/thanos_overview.md) — архитектура Thanos.
- [Мультикластерный remote_write в VictoriaMetrics](./multi-cluster-remote-write-victoria-metrics.md) — spoke-to-infra паттерн с kube-prom-stack и Kustomize.
