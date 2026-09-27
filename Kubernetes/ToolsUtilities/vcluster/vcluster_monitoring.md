# vCluster — мониторинг и Observability

> Документ описывает полный стек наблюдаемости для vCluster: метрики Control Plane, логи Syncer, алертинг, дашборды и интеграцию с Prometheus/Grafana/Loki. Архитектура и компоненты — в [обзоре](./vcluster_overview.md), безопасность — в [vcluster_security_and_sync.md](./vcluster_security_and_sync.md), troubleshooting — в [vcluster_troubleshooting.md](./vcluster_troubleshooting.md).

## Определения

**Observability (Наблюдаемость)** — способность внешнего наблюдателя делать выводы о внутреннем состоянии системы по её внешним проявлениям: метрикам, логам и трейсам. Для vCluster наблюдаемость охватывает три уровня: хост-кластер, Control Plane виртуального кластера и workload-приложения тенанта.

**Prometheus** — система мониторинга и алертинга, работающая по pull-модели (scrape). Собирает метрики с HTTP-эндпоинтов, хранит временные ряды и генерирует алерты по PromQL-выражениям.

**Grafana** — платформа визуализации метрик. Подключается к Prometheus (или Loki) как источник данных и отображает дашборды с графиками, таблицами и тепловыми картами.

**Loki** — система сбора и анализа логов, совместимая с PromQL. Агрегирует логи по labels (namespace, pod, container) без полнотекстового индексирования, что снижает потребление диска.

**ServiceMonitor** — CRD Prometheus Operator, описывающий, как Prometheus должен скрапить метрики с一组 подов (по labels, порту, интервалу). Автоматически создаёт scrape-конфиг при установке Prometheus Operator.

**kube-state-metrics** — компонент, генерирующий метрики состояния Kubernetes-объектов (Pods, Deployments, Nodes, PVC) из API-сервера. Не показывает производительность, но отражает желаемое и текущее состояние.

**node-exporter** — агент, собирающий аппаратные метрики узла (CPU, RAM, Disk, Network) и предоставляющий их на HTTP-эндпоинте `/metrics`.

**Alertmanager** — компонент стека Prometheus, отвечающий за маршрутизацию, дедупликацию и доставку алертов (email, Slack, PagerDuty, webhook).

**Textfile Collector** — плагин node-exporter, позволяющий кастомные метрики записывать в `.prom`-файлы на диске. Используется для метрик, которые не собираются стандартными агентами (например, WireGuard handshake).

## Основные концепции

### Три уровня метрик vCluster

Мониторинг vCluster требует сбора метрик на трёх уровнях, каждый из которых отвечает за свой слой стека:

| Уровень | Что мониторить | Источник | Инструменты |
| :--- | :--- | :--- | :--- |
| **Хост-кластер** | Физические узлы, поды Syncer, namespace vCluster | API-сервер хоста | Prometheus + kube-state-metrics + node-exporter |
| **Control Plane vCluster** | API-сервер виртуального кластера, etcd/SQLite, Scheduler | Метрики на `:8443/metrics` | Prometheus Operator (ServiceMonitor) внутри vCluster |
| **Workload тенанта** | Приложения, развернутые внутри vCluster | Стандартные метрики приложений | Prometheus/Grafana внутри vCluster |

### Архитектура сбора метрик

```text
┌─────────────────────────────────────────────────────────────────┐
│                    Host Cluster                                  │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │ Prometheus (central)                                        │ │
│  │   ├── scrape: kube-state-metrics (host)                     │ │
│  │   ├── scrape: node-exporter (host nodes)                    │ │
│  │   ├── scrape: vCluster Syncer (port 8443/metrics)           │ │
│  │   ├── scrape: vCluster API (port 8443/metrics)              │ │
│  │   └── scrape: ServiceMonitor inside vCluster                │ │
│  └─────────────────────────────────────────────────────────────┘ │
│         │                        │                               │
│         ▼                        ▼                               │
│  ┌─────────────┐        ┌─────────────────┐                     │
│  │  Grafana    │        │   Alertmanager   │                     │
│  │  (dashboards)│        │  (Slack/PD)      │                     │
│  └─────────────┘        └─────────────────┘                     │
└─────────────────────────────────────────────────────────────────┘
         │
         │ scrape (через port-forward или Service)
         ▼
┌─────────────────────────────────────────────────────────────────┐
│                    vCluster Namespace                            │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │ Prometheus Operator (опционально)                           │ │
│  │   ├── ServiceMonitor: vCluster API Server                   │ │
│  │   └── PrometheusRule: виртуальные алерты                    │ │
│  └─────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

### Метрики Syncer — ключевые индикаторы здоровья

Syncer — критический компонент, его метрики отражают здоровье синхронизации:

| Метрика | Тип | Описание | Порог алерта |
| :--- | :--- | :--- | :--- |
| `vcluster_syncer_sync_errors_total` | Counter | Общее число ошибок синхронизации | > 0 в течение 5 минут |
| `vcluster_syncer_sync_duration_seconds` | Histogram | Время синхронизации одного объекта | p95 > 2s |
| `vcluster_syncer_watch_errors_total` | Counter | Ошибки watch-соединения с API | > 5 в течение 5 минут |
| `vcluster_syncer_reconcile_total` | Counter | Число реконсиляций объектов | Резкий рост — деградация |
| `vcluster_syncer_objects_total` | Gauge | Количество синхронизированных объектов | Резкое падение — проблема |

### Метрики API-сервера vCluster

Стандартные метрики kube-apiserver, доступные на `:8443/metrics`:

| Метрика | Описание | Важность |
| :--- | :--- | :--- |
| `apiserver_request_duration_seconds` | Латентность запросов к API | Высокая — показывает задержки для тенантов |
| `apiserver_request_total` | Общее число запросов | Средняя — для оценки нагрузки |
| `apiserver_current_inflight_requests` | Активные запросы | Высокая — перегрузка API |
| `etcd_request_duration_seconds` | Время операций с etcd | Высокая — проблемы с хранилищем |
| `watch_cache_initializations_total` | Инициализации watch | Средняя — проблемы с large lists |

### Метрики etcd/Backing Store

| Метрика | Описание | Порог алерта |
| :--- | :--- | :--- |
| `etcd_server_has_leader` | Наличие лидера (0 = нет) | 0 — критично |
| `etcd_server_leader_changes_seen_total` | Смены лидера | > 3 в час |
| `etcd_disk_wal_fsync_duration_seconds` | Время fsync WAL | p99 > 10ms |
| `etcd_disk_backend_commit_duration_seconds` | Время коммита в backend | p99 > 25ms |
| `etcd_server_proposals_failed_total` | Проваленные предложения | Рост — проблема с кворумом |

### Метрики хост-кластера для vCluster

| Метрика | Что показывает | Источник |
| :--- | :--- | :--- |
| `kube_pod_info{pod=~"vcluster-.*"}` | Информация о подах vCluster | kube-state-metrics |
| `kube_pod_container_resource_requests` | Запрошенные ресурсы Control Plane | kube-state-metrics |
| `kube_pod_container_status_restarts_total` | Рестарты контейнеров vCluster | kube-state-metrics |
| `node_cpu_seconds_total` | Загрузка CPU узлов | node-exporter |
| `node_memory_MemAvailable_bytes` | Доступная память узлов | node-exporter |

### Алертинг: ключевые правила

#### Критические алерты (немедленное уведомление)

```yaml
# prometheus-rules-vcluster.yaml
groups:
  - name: vcluster-critical
    rules:
      - alert: VClusterSyncerErrors
        expr: |
          rate(vcluster_syncer_sync_errors_total[5m]) > 0
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "vCluster {{ $labels.vcluster }}: ошибки синхронизации"
          description: >
            Syncer в namespace {{ $labels.namespace }} сообщает об ошибках
            синхронизации более 5 минут. Тенант может терять доступ к ресурсам.

      - alert: VClusterAPIServerDown
        expr: |
          up{job="vcluster-api", namespace=~".*"} == 0
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "vCluster API Server недоступен"
          description: >
            API-сервер vCluster не отвечает на scrape-запросы более 2 минут.
            Тенант не может управлять ресурсами.

      - alert: VClusterEtcdNoLeader
        expr: |
          etcd_server_has_leader{job=~"vcluster-.*"} == 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "vCluster etcd потерял лидера"
          description: >
            etcd в backing store vCluster не имеет лидера.
            Control Plane полностью неработоспособен.
```

#### Предупреждения (warning)

```yaml
  - name: vcluster-warning
    rules:
      - alert: VClusterSyncerHighLatency
        expr: |
          histogram_quantile(0.95,
            rate(vcluster_syncer_sync_duration_seconds_bucket[5m])
          ) > 2
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "vCluster: высокая латентность Syncer"
          description: >
            p95 латентности синхронизации превышает 2 секунды.
            Возможны задержки в обновлении статусов подов.

      - alert: VClusterPodRestarts
        expr: |
          increase(kube_pod_container_status_restarts_total{
            pod=~"vcluster-.*"
          }[1h]) > 3
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "vCluster: частые рестарты контейнеров"
          description: >
            Контейнер {{ $labels.container }} в поде {{ $labels.pod }}
            перезапустился более 3 раз за час.

      - alert: VClusterEtcdHighDiskLatency
        expr: |
          histogram_quantile(0.99,
            rate(etcd_disk_wal_fsync_duration_seconds_bucket[5m])
          ) > 0.01
        for: 15m
        labels:
          severity: warning
        annotations:
          summary: "vCluster etcd: высокая задержка диска"
          description: >
            p99 задержки fsync WAL etcd превышает 10ms.
            Возможно, проблемы с диском или I/O.
```

## Практические сценарии

### Настройка scrape метрик vCluster в Prometheus

#### Вариант 1: Prometheus Operator на хосте (ServiceMonitor)

Если Prometheus Operator развёрнут на хост-кластере, ServiceMonitor автоматически настроит scrape:

```yaml
# vcluster-servicemonitor.yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: vcluster-api
  namespace: monitoring
  labels:
    release: prometheus  # привязка к Prometheus-инстансу
spec:
  namespaceSelector:
    matchNames:
      - team-alpha  # namespace vCluster на хосте
  selector:
    matchLabels:
      app: vcluster
  endpoints:
    - port: https
      scheme: https
      tlsConfig:
        insecureSkipVerify: true  # vCluster использует свой CA
      path: /metrics
      interval: 30s
      scrapeTimeout: 10s
```

#### Вариант 2: Prometheus без Operator (ручной scrape)

Добавить в `prometheus.yml`:

```yaml
scrape_configs:
  - job_name: 'vcluster-syncer'
    kubernetes_sd_configs:
      - role: pod
        namespaces:
          names:
            - team-alpha  # namespace vCluster
    relabel_configs:
      - source_labels: [__meta_kubernetes_pod_label_app]
        regex: vcluster
        action: keep
      - source_labels: [__meta_kubernetes_pod_annotation_prometheus_io_port]
        action: replace
        target_label: __address__
        regex: (.+)
        replacement: ${1}:8443
```

#### Вариант 3: Scraping метрик workload'ов тенанта

Workload-приложения внутри vCluster не видны Prometheus на хосте. Два подхода:

**Подход A:** Prometheus внутри vCluster (изолированный мониторинг)

```yaml
# vcluster.yaml тенанта
controlPlane:
  distro:
    k8s:
      enabled: true

# Тенант разворачивает свой Prometheus Operator внутри vCluster
```

**Подход B:** Federation — Prometheus на хосте забирает метрики из vCluster

```yaml
# prometheus.yml на хосте
scrape_configs:
  - job_name: 'vcluster-federation'
    honor_labels: true
    metrics_path: '/federate'
    params:
      'match[]':
        - '{job=~".+"}'
    static_configs:
      - targets:
          - 'vcluster-api.team-alpha.svc:8443'  # через Service
```

### Настройка Loki для сбора логов Syncer

Syncer пишет структурированные JSON-логи в stdout. Promtail или Loki-агент собирает их по labels:

```yaml
# promtail-config.yaml
server:
  http_listen_port: 9080

positions:
  filename: /tmp/positions.yaml

clients:
  - url: http://loki:3100/loki/api/v1/push

scrape_configs:
  - job_name: vcluster-syncer
    kubernetes_sd_configs:
      - role: pod
        namespaces:
          names:
            - team-alpha
    relabel_configs:
      - source_labels: [__meta_kubernetes_pod_label_app]
        regex: vcluster
        action: keep
      - source_labels: [__meta_kubernetes_pod_container_name]
        target_label: container
      - source_labels: [__meta_kubernetes_namespace]
        target_label: namespace
      - source_labels: [__meta_kubernetes_pod_label_vcluster_loft_sh_name]
        target_label: vcluster
    pipeline_stages:
      - json:
          expressions:
            level: level
            msg: msg
            err: err
      - labels:
          level:
          msg:
```

#### Ключевые логи для алертинга

| Паттерн лога | Уровень | Действие |
| :--- | :--- | :--- |
| `failed to sync resource` | ERROR | Проверить RBAC Syncer, CRD на хосте |
| `backing store unavailable` | CRITICAL | Проверить etcd/SQLite, перезапустить Control Plane |
| `watch timeout exceeded` | WARNING | Проверить нагрузку на API, увеличить `--sync-interval` |
| `connection to host API lost` | CRITICAL | Проверить сетевую доступность, NetworkPolicy |
| `certificate has expired` | CRITICAL | Ротировать сертификаты, перезапустить под |

### Настройка Grafana-дашбордов

#### Дашборд Health Overview

Основные панели для мониторинга состояния vCluster:

| Панель | Тип | Запрос | Описание |
| :--- | :--- | :--- | :--- |
| Syncer Status | Stat | `up{job="vcluster-syncer"}` | 1 = работает, 0 = упал |
| Sync Errors Rate | Time Series | `rate(vcluster_syncer_sync_errors_total[5m])` | Частота ошибок синхронизации |
| API Latency (p95) | Time Series | `histogram_quantile(0.95, rate(apiserver_request_duration_seconds_bucket[5m]))` | Задержка API |
| Active Objects | Gauge | `vcluster_syncer_objects_total` | Число синхронизированных объектов |
| Pod Restarts | Bar Gauge | `increase(kube_pod_container_status_restarts_total{pod=~"vcluster-.*"}[1h])` | Рестарты за час |
| etcd Leader | Stat | `etcd_server_has_leader` | Наличие лидера |

#### Дашборд Resource Usage

| Панель | Тип | Запрос |
| :--- | :--- | :--- |
| CPU Usage | Time Series | `rate(container_cpu_usage_seconds_total{pod=~"vcluster-.*"}[5m])` |
| Memory Usage | Time Series | `container_memory_working_set_bytes{pod=~"vcluster-.*"}` |
| CPU Requests vs Limits | Stacked | `kube_pod_container_resource_requests vs limits` |
| Disk Usage | Gauge | `node_filesystem_avail_bytes` |

### Smoke-test: проверка сбора метрик

```bash
# 1. Проверить, что Syncer отдаёт метрики
kubectl -n team-alpha port-forward svc/vcluster 8443:8443 &
curl -sk https://localhost:8443/metrics | head -20
# → vcluster_syncer_sync_errors_total 0
# → vcluster_syncer_objects_total 42

# 2. Проверить, что Prometheus скрапит
kubectl -n monitoring port-forward svc/prometheus 9090:9090 &
curl -s 'http://localhost:9090/api/v1/targets' | jq '.data.activeTargets[] | select(.labels.job=="vcluster-syncer") | .health'
# → "up"

# 3. Проверить Loki
curl -s 'http://localhost:3100/loki/api/v1/query?query={namespace="team-alpha"}' | jq '.data.result | length'
# → число серий > 0
```

### Диагностика проблем мониторинга

| Симптом | Вероятная причина | Решение |
| :--- | :--- | :--- |
| Prometheus не скрапит vCluster | ServiceMonitor не найден или labels не совпадают | `kubectl get servicemonitors -A`; проверить labels `release` |
| Метрики `up == 0` для vCluster | API-сервер недоступен из namespace monitoring | Проверить NetworkPolicy, разрешить трафик на порт 8443 |
| Loki не показывает логи Syncer | Promtail не находит поды по labels | Проверить `vcluster_loft_sh_name` label на подах Syncer |
| Grafana дашборд пустой | Источник данных (datasource) неправильно настроен | Проверить настройки Prometheus/Loki в Grafana → Configuration → Data Sources |
| Алерты не срабатывают | Alertmanager не подключен к Prometheus | `amtool config show` на Alertmanager; проверить `alerting` секцию в prometheus.yml |
| Дублирующиеся метрики | Prometheus Operator скрапит несколько раз | Проверить, нет ли двух ServiceMonitor для одного vCluster |

### Лучшие практики мониторинга

- **Изоляция метрик:** Используйте `namespaceSelector` в ServiceMonitor, чтобы Prometheus скрапил только нужные vCluster, а не все.
- **Retention:** Для метрик vCluster установите retention 30 дней (для troubleshooting) и 90 дней (для compliance). Логи — 14 дней в hot storage, 90 дней в cold.
- **Дашборды per-tenant:** Создавайте отдельные Grafana-дашборды для каждого тенанта с фильтрацией по `vcluster` label.
- **Recording rules:** Для частых PromQL-запросов (p95 latency, error rate) создавайте recording rules, чтобы не нагружать Prometheus при рендере дашбордов.
- **Мониторинг самого мониторинга:** Алерт на `up == 0` для Prometheus и Loki. Если мониторинг упал — вы слепы к проблемам vCluster.
- **Базelines:** Установите baseline метрик в спокойном состоянии (normal baseline), чтобы аномалии детектировались через отклонение.

## Дополнительная информация

### Внутренние ссылки

- [vCluster — обзор и архитектура](./vcluster_overview.md)
- [vCluster — безопасность и синхронизация](./vcluster_security_and_sync.md)
- [vCluster — troubleshooting](./vcluster_troubleshooting.md)

### См. также

- [Prometheus — установка и конфигурация](../../Prometheus/installation/prometheus_server_installation.md)
- [Grafana — обзор](../../Grafana/grafana_overview.md)
- [Loki — установка стека](../../Loki/loki_stack_setup/)

### Внешние ссылки

- [vCluster Observability Documentation](https://www.vcluster.com/docs/monitoring)
- [Prometheus Operator — ServiceMonitor](https://prometheus-operator.dev/docs/user-guides/service-monitoring/)
- [Grafana Dashboards for Kubernetes](https://grafana.com/grafana/dashboards/)
