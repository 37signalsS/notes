# Логирование K3s: Loki + Alloy

Руководство по централизованному сбору логов в K3s с использованием Grafana Loki и Alloy (заменяет Promtail). Описывает установку через Helm, конфигурацию сбора логов из подов и нод, запросы через LogQL.

Контекст: Часть серии по созданию dev-окружения в K3s. Логи GitLab, Harbor, ArgoCD и dev-контейнеров собираются централизованно. См. [Архитектура K3s](./k3s_architecture.md), [Мониторинг](./k3s_monitoring.md).

---

## Определения

| Термин | Описание |
| :--- | :--- |
| **Grafana Loki** | Indexed storage для логов (Anbi-индексация через labels). Хранит логи в Object Storage (Minio/S3) и индексы в boltdb-shipper. Не индексирует содержимое логов. |
| **Grafana Alloy** | Универсальный агент телеметрии (метрики, логи, трейсы), заменяющий Promtail и Grafana Agent. Конфигурируется через River (HCL-подобный синтаксис). |
| **LogQL** | Язык запросов Loki для фильтрации и агрегации логов. Синтаксис похож на PromQL +管道ные операторы. |
| **Push API** | HTTP API Loki для приема логов от агентов (`/loki/api/v1/push`). Агенты (Alloy) отправляют логи на этот эндпоинт. |
| **Structured Metadata** | Механизм Loki 3.x для передачи дополнительных метаданных (traceID, level) без увеличения cardinality индекса. |
| **Bloom Filters** | Структура данных в Loki 3.x для ускорения поиска по логам без полного сканирования TSDB. |

Навигация: [Loki Overview](../../Loki/loki_overview.md) | [Alloy Overview](../../Grafana/grafana_alloy_overview.md) | [LogQL Examples](../../Loki/loki_stack_setup/logql_examples.md)

---

## Основные концепции

### Архитектура логирования в K3s

```text
┌─────────────────────────────────────────────────────────────────┐
│                     K3s Cluster                                  │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌──────────────┐     logs      ┌──────────────────────────────┐ │
│  │ Alloy        │ ────────────▶ │           Loki               │ │
│  │ (DaemonSet)  │   push API    │         (SSD mode)           │ │
│  │              │               │                              │ │
│  │ Logs from:   │               │  ┌────────┐  ┌────────────┐  │ │
│  │  - /var/log/ │               │  │ Ingester│  │ Querier    │  │ │
│  │  - journald  │               │  └────────┘  └────────────┘  │ │
│  │  - containers│               │                              │ │
│  └──────────────┘               │  Storage: Minio (10Gi PVC)  │ │
│                                  └──────────┬─────────────────┘  │
│                                             │                     │
│  ┌──────────────┐    LogQL      ┌──────────▼─────────────────┐  │
│  │   Grafana    │ ◀──────────── │  Loki API                  │  │
│  │   (Query)    │               │  /loki/api/v1/query_range  │  │
│  └──────────────┘               └────────────────────────────┘  │
│                                                                  │
│  Логи K3s Control Plane:                                         │
│  ┌──────────────────────────────────────────────────────────────┐ │
│  │ journald → alloy → loki                                      │ │
│  │  - k3s.service (API Server, scheduler, controller-manager)   │ │
│  │  - k3s-agent.service (kubelet, containerd)                   │ │
│  └──────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

### Источники логов в K3s

| Источник | Метод сбора | Пример лога |
| :--- | :--- | :--- |
| **Pod logs** | Alloy container discovery | `kubectl logs <pod>` |
| **journald (k3s.service)** | Alloy journald receiver | `journalctl -u k3s` |
| **journald (k3s-agent.service)** | Alloy journald receiver | `journalctl -u k3s-agent` |
| **containerd** | Alloy containerd plugin | Runtime logs |
| **NGINX Ingress** | Alloy log files | Access/error logs |
| **GitLab** | Application logs + journald | Sidekiq, Puma, Gitaly |
| **Harbor** | Application logs | Core, Registry, Trivy |

### Ресурсные требования

| Компонент | CPU Request | Memory Request | PVC | Примечание |
| :--- | :--- | :--- | :--- | :--- |
| **Loki (SSD mode)** | 500m | 1Gi | 10Gi | Single-binary для dev |
| **Alloy (DaemonSet)** | 100m | 128Mi | - | На каждой ноде |
| **Итого** | ~600m | ~1.3Gi | ~10Gi | Дополнительно к Prometheus |

---

## Требования и предварительная подготовка

### Программные зависимости

| Компонент | Минимальная версия | Рекомендация |
| :--- | :--- | :--- |
| **K3s** | v1.28+ | v1.36.3+k3s1 |
| **Helm** | 3.14+ | v4.2.3 |
| **StorageClass** | `local-path` | Для PVC Loki |
| **Grafana** | Установлен | Для визуализации логов (см. [Мониторинг](./k3s_monitoring.md)) |

---

## Практические сценарии

### 1. Установка Loki (SingleBinary через Helm)

```bash
# Добавление репозитория Grafana
helm repo add grafana https://grafana.github.io/helm-charts
helm repo update

# Установка Loki в режиме SingleBinary (для dev-окружений)
helm install loki grafana/loki \
  --namespace monitoring \
  --set deploymentMode=SingleBinary \
  --set singleBinary.replicas=1 \
  --set loki.auth_enabled=false \
  --set loki.commonConfig.replication_factor=1 \
  --set loki.storage.type.filesystem \
  --set loki.storage.filesystem.chunks_directory=/var/loki/chunks \
  --set loki.storage.filesystem.rules_directory=/var/loki/rules \
  --set singleBinary.persistence.size=10Gi \
  --set singleBinary.persistence.storageClass=local-path \
  --set gateway.enabled=false \
  --set read.replicas=0 \
  --set write.replicas=0 \
  --set backend.replicas=0

# Ожидание готовности
kubectl -n monitoring get pods -w | grep loki
# → loki-0                              1/1     Running   0          60s

# Проверка сервиса
kubectl -n monitoring get svc loki
# → NAME    TYPE        CLUSTER-IP    EXTERNAL-IP   PORT(S)
# → loki    ClusterIP   10.43.x.x     <none>        3100/TCP
```

### 2. Установка Alloy (DaemonSet для сбора логов)

```bash
# Установка Alloy через Helm
helm install alloy grafana/alloy \
  --namespace monitoring \
  --set deployment.mode=DaemonSet \
  --set config.mapContent='
    logging {
      level = "info"
      format = "logfmt"
    }

    discovery.kubernetes "pods" {
      role = "pod"
    }

    discovery.kubernetes "nodes" {
      role = "nodes"
    }

    // Сбор логов из подов (container logs)
    loki.source.kubernetes "pods" {
      targets    = discovery.kubernetes.pods.targets
      forward_to = [loki.write.local.receiver]
    }

    // Сбор логов из journald (K3s control plane)
    loki.source.journald "k3s" {
      path       = "/var/log/journal/"
      job_label  = "k3s"
      forward_to = [loki.write.local.receiver]
    }

    loki.write "local" {
      endpoint {
        url = "http://loki.monitoring.svc:3100/loki/api/v1/push"
      }
    }
  '

# Ожидание готовности
kubectl -n monitoring get pods -w | grep alloy
# → alloy-xxxxx                          1/1     Running   0          30s
```

### 3. Проверка сбора логов

```bash
# Проверка, что Loki принимает логи
kubectl -n monitoring exec loki-0 -- wget -qO- 'http://localhost:3100/ready'
# → ready

# Запрос логов через Loki API
kubectl -n monitoring exec loki-0 -- wget -qO- \
  'http://localhost:3100/loki/api/v1/query_range?query={job="k3s"}&limit=5' | jq '.data.result[0].values[0]'
# → [1234567890, "log line from k3s..."]

# Проверка метрик Loki
kubectl -n monitoring exec loki-0 -- wget -qO- 'http://localhost:3100/metrics' | grep loki_ingester_memory_chunks
```

### 4. Настройка Grafana datasource для Loki

```bash
# Через Grafana UI: Configuration -> Data Sources -> Add -> Loki
# URL: http://loki.monitoring.svc:3100

# Или через provisioning (ConfigMap)
cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: ConfigMap
metadata:
  name: grafana-datasource-loki
  namespace: monitoring
  labels:
    grafana_datasource: "1"
data:
  loki.yaml: |
    apiVersion: 1
    datasources:
      - name: Loki
        type: loki
        access: proxy
        url: http://loki.monitoring.svc:3100
        isDefault: false
        editable: true
EOF
```

### 5. Запросы LogQL (примеры)

```bash
# Все логи из namespace gitlab
{namespace="gitlab"}

# Логи с ошибками из GitLab Webservice
{namespace="gitlab", app="webservice"} |= "error"

# Логи K3s control plane
{job="k3s"} | logfmt | level="error"

# Подсчет логов по уровням за последний час
sum by (level) (count_over_time({namespace="gitlab"} | logfmt | __error__="" [1h]))

# Логи с определенным traceID (Structured Metadata)
{namespace="gitlab"} | json | traceID="abc123"

# Топ-10 подов по количеству логов за 5 минут
topk(10, sum by (pod) (count_over_time({namespace="gitlab"} [5m])))
```

### 6. Настройка retention policy в Loki

```yaml
# loki-config-runtime.yaml — переопределение через Helm values
loki:
  limits_config:
    retention_period: 7d
    max_query_series: 5000
    ingestion_rate_mb: 10
    ingestion_burst_size_mb: 20

  storageConfig:
    filesystem:
      directory: /var/loki/chunks

  compactor:
    compaction_interval: 10m
    retention_enabled: true
    retention_delete_delay: 2h
    retention_delete_worker_count: 150
```

```bash
# Применение через обновление Helm-чарта
helm upgrade loki grafana/loki \
  --namespace monitoring \
  --reuse-values \
  --set loki.limits_config.retention_period=7d \
  --set loki.compactor.retention_enabled=true
```

---

## Типичные ошибки и устранение неполадок

### Ошибка: Alloy не отправляет логи в Loki

```bash
# Проверка логов Alloy
kubectl -n monitoring logs -l app.kubernetes.io/name=alloy --tail=50
# → Ищите "error" или "failed to push"

# Проверка доступности Loki из пода Alloy
kubectl -n monitoring exec $(kubectl -n monitoring get pods -l app.kubernetes.io/name=alloy -o name | head -1) -- \
  wget -qO- 'http://loki.monitoring.svc:3100/ready'
# → ready

# Если ошибка DNS: проверьте CoreDNS
kubectl -n kube-system get pods | grep coredns
```

### Ошибка: Loki не принимает данные (ingestion rate limit)

```bash
# Проверка лимитов
kubectl -n monitoring exec loki-0 -- wget -qO- 'http://localhost:3100/metrics' | grep loki_ingester_samples_per_chunk

# Увеличение лимитов
helm upgrade loki grafana/loki \
  --namespace monitoring \
  --reuse-values \
  --set loki.limits_config.ingestion_rate_mb=20 \
  --set loki.limits_config.ingestion_burst_size_mb=40
```

### Ошибка: Disk usage растет слишком быстро

```bash
# Проверка размера данных
kubectl -n monitoring exec loki-0 -- du -sh /var/loki/chunks/

# Настройка агрессивной очистки
helm upgrade loki grafana/loki \
  --namespace monitoring \
  --reuse-values \
  --set loki.limits_config.retention_period=3d \
  --set loki.compactor.compaction_interval=5m

# Ручная очистка (при необходимости)
kubectl -n monitoring exec loki-0 -- rm -rf /var/loki/chunks/fake/
```

---

## Дополнительная информация

### Замена Promtail на Alloy

Начиная с весны 2026 года, Promtail находится в EOL. Alloy является рекомендуемой заменой:

| Аспект | Promtail | Alloy |
| :--- | :--- | :--- |
| **Статус** | EOL (Spring 2026) | Active development |
| **Конфигурация** | YAML | River (HCL-like) |
| **Функции** | Только логи | Метрики + логи + трейсы |
| **Дисковый кэш** | Нет | Встроенный WAL |
| **Интеграция** | Только Loki | Prometheus, Tempo, Loki |

### Предупреждения

| Аспект | Риск | Рекомендация |
| :--- | :--- | :--- |
| **Filesystem storage** | Нет репликации, потеря при удалении PVC | Используйте Minio/S3 для продакшена |
| **Retention** | Диск заполняется | Настройте retention=7d для dev |
| **Cardinality** | Высокая cardinality labels → рост индекса | Используйте ≤10 уникальных label'ов |
| **journald** | Логи K3s пишутся в journald, не в файлы | Alloy должен иметь доступ к `/var/log/journal/` |

### См. также

- [Loki Overview](../../Loki/loki_overview.md) -- архитектура и концепции Loki
- [Alloy Overview](../../Grafana/grafana_alloy_overview.md) -- обзор Alloy
- [LogQL Examples](../../Loki/loki_stack_setup/logql_examples.md) -- примеры запросов
- [Мониторинг K3s](./k3s_monitoring.md) -- Prometheus + Grafana
- [Grafana](../../Grafana/grafana_overview.md) -- дашборды и визуализация
