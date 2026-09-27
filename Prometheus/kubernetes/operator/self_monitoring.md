# Мониторинг Prometheus Operator (Self-Monitoring)

## Определения

**Self-Monitoring Prometheus Operator** — практика мониторинга самого стека мониторинга: метрики reconciliation Controller, здоровье Prometheus TSDB, доступность Alertmanager, корректность config-reloader. Саммониторинг обеспечивает обнаружение сбоев Operator ДО того, как они повлияют на метрики приложений.

**Reconciliation Lag** — время между изменением CRD и применением нового конфигурации в кластере. Высокий lag (>30 секунд) указывает на проблемы с API-сервером, etcd или перегрузкой Operator.

**Config-Reloader Health** — метрики sidecar-контейнера, отслеживающего изменения в Secret/ConfigMap и инициирующего перезагрузку Prometheus через `/-/reload`. Сбой config-reloader означает, что новые ServiceMonitor/PrometheusRule не применяются.

> **Смотрите также:** [Концепции](./concepts.md) — ключевые метрики Operator; [Troubleshooting](./troubleshooting.md) — диагностика сбоев.

---

## Базовые концепции

### Ключевые метрики Operator

| Метрика | Описание | Критический порог |
|:---|:---|:---|
| `prometheus_operator_reconcile_errors_total` | Ошибки reconciliation | > 0 в течение 5 минут |
| `prometheus_operator_reconcile_duration_seconds` | Длительность reconciliation | P99 > 30 секунд |
| `prometheus_operator_config_size_bytes` | Размер сгенерированного конфига | > 800 KB (лимит Secret — 1 MB) |
| `prometheus_config_last_reload_success_timestamp_seconds` | Время последнего успешного reload | Разница с текущим временем > 5 минут |
| `prometheus_operator_workqueue_depth` | Глубина очереди работ | > 100 |

### Метрики Prometheus TSDB

| Метрика | Описание | Критический порог |
|:---|:---|:---|
| `prometheus_tsdb_head_series` | Количество активных серий | > 1M (риск OOM) |
| `prometheus_tsdb_head_chunks` | Количество чанков в Head Block | Рост > 20% в час |
| `prometheus_tsdb_wal_corruptions_total` | Коррупции WAL | > 0 |
| `prometheus_tsdb_compaction_chunks_range` | Диапазон чанков compaction | Зависание > 1 часа |
| `prometheus_engine_queries_active` | Активные PromQL-запросы | > 100 (троттлинг) |

### Метрики Remote Write

| Метрика | Описание | Критический порог |
|:---|:---|:---|
| `prometheus_remote_storage_shards` | Количество шардов очереди | Рост > 20% за час |
| `prometheus_remote_storage_dropped_samples_total` | Потерянные сэмплы | > 0 за час |
| `prometheus_remote_storage_samples_pending` | Сэмплы в очереди | Рост > 10% за 15 минут |
| `prometheus_remote_storage_highest_timestamp_in_seconds` - `queue_highest_sent_timestamp_seconds` | Лаг отправки | > 5 минут |

### Метрики Alertmanager

| Метрика | Описание | Критический порог |
|:---|:---|:---|
| `alertmanager_cluster_members` | Участники кластера | < 3 (для 3 реплик) |
| `alertmanager_notifications_failed_total` | Неудачные уведомления | > 0 за час |
| `alertmanager_config_last_reload_successful` | Успешность reload конфига | == 0 |

---

## Практические сценарии

### PrometheusRule для саммониторинга Operator

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: operator-self-monitoring
  namespace: monitoring
  labels:
    release: monitoring
spec:
  groups:
    - name: operator-health
      rules:
        # Ошибки reconciliation
        - alert: PrometheusOperatorReconcileErrors
          expr: rate(prometheus_operator_reconcile_errors_total[5m]) > 0.1
          for: 5m
          labels:
            severity: critical
          annotations:
            summary: "Prometheus Operator: ошибки reconciliation"
            description: "{{ $value }} ошибок в минуту в namespace {{ $labels.namespace }}"

        # Медленный reconciliation
        - alert: PrometheusOperatorReconcileSlow
          expr: histogram_quantile(0.99, rate(prometheus_operator_reconcile_duration_seconds_bucket[5m])) > 30
          for: 10m
          labels:
            severity: warning
          annotations:
            summary: "Prometheus Operator: медленный reconciliation"
            description: "P99 reconciliation: {{ $value }} секунд"

        # Конфиг слишком большой
        - alert: PrometheusOperatorConfigTooLarge
          expr: prometheus_operator_config_size_bytes > 800000
          for: 10m
          labels:
            severity: warning
          annotations:
            summary: "Конфиг Prometheus близок к лимиту Secret (1MB)"
            description: "Размер: {{ $value | humanize1024 }}B"

        # Очередь работ переполнена
        - alert: PrometheusOperatorWorkqueueBacklog
          expr: prometheus_operator_workqueue_depth > 100
          for: 15m
          labels:
            severity: warning
          annotations:
            summary: "Очередь работ Operator переполнена"
            description: "Глубина очереди: {{ $value }}"

    - name: prometheus-tsdb-health
      rules:
        # Конфиг не перезагружается
        - alert: PrometheusConfigReloadFailed
          expr: prometheus_config_last_reload_success_timestamp_seconds < time() - 300
          for: 5m
          labels:
            severity: critical
          annotations:
            summary: "Prometheus: конфиг не перезагружается"
            description: "Последний успешный reload более 5 минут назад"

        # WAL corrupted
        - alert: PrometheusWALCorrupted
          expr: increase(prometheus_tsdb_wal_corruptions_total[1h]) > 0
          for: 0m
          labels:
            severity: critical
          annotations:
            summary: "Prometheus: повреждение WAL"
            description: "Требуется очистка /wal"

        # Кардинальность >1M
        - alert: PrometheusCardinalityHigh
          expr: prometheus_tsdb_head_series > 1000000
          for: 1h
          labels:
            severity: warning
          annotations:
            summary: "Превышен порог кардинальности (>1M серий)"
            description: "Активных серий: {{ $value }}"

        # Прогноз переполнения диска
        - alert: PrometheusTSDBDiskWillFull
          expr: predict_linear(prometheus_tsdb_storage_blocks_bytes[6h], 7*24*3600) > 90*1024*1024*1024
          for: 30m
          labels:
            severity: warning
          annotations:
            summary: "TSDB вырастет до 90GB через 7 дней"

    - name: remote-write-health
      rules:
        # Remote Write: теряются сэмплы
        - alert: PrometheusRemoteWriteDropped
          expr: increase(prometheus_remote_storage_dropped_samples_total[1h]) > 0
          for: 5m
          labels:
            severity: critical
          annotations:
            summary: "Remote Write: теряются сэмплы"
            description: "Потеряно {{ $value }} сэмплов за час"

        # Remote Write: лаг >5 минут
        - alert: PrometheusRemoteWriteLag
          expr: |
            prometheus_remote_storage_highest_timestamp_in_seconds
            - prometheus_remote_storage_queue_highest_sent_timestamp_seconds > 300
          for: 10m
          labels:
            severity: warning
          annotations:
            summary: "Remote Write: лаг >5 минут"
            description: "Лаг: {{ $value }} секунд"

        # Remote Write: рост шардов
        - alert: PrometheusRemoteWriteShardGrowth
          expr: rate(prometheus_remote_storage_shards[1h]) > 0.1
          for: 30m
          labels:
            severity: warning
          annotations:
            summary: "Remote Write: растет количество шардов"
            description: "Текущее значение: {{ $value }}"

    - name: alertmanager-health
      rules:
        # Кластер Alertmanager: мало участников
        - alert: AlertmanagerClusterTooSmall
          expr: alertmanager_cluster_members < 3
          for: 5m
          labels:
            severity: critical
          annotations:
            summary: "Alertmanager: кластер меньше кворума"
            description: "Участников: {{ $value }}"

        # Конфиг Alertmanager не перезагружается
        - alert: AlertmanagerConfigReloadFailed
          expr: alertmanager_config_last_reload_successful == 0
          for: 5m
          labels:
            severity: critical
          annotations:
            summary: "Alertmanager: конфиг не перезагружается"

        # Неудачные уведомления
        - alert: AlertmanagerNotificationsFailed
          expr: rate(alertmanager_notifications_failed_total[1h]) > 0
          for: 10m
          labels:
            severity: critical
          annotations:
            summary: "Alertmanager: неудачные уведомления"
            description: "{{ $value }} ошибок в час"
```

### ServiceMonitor для самого Operator

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: prometheus-operator
  namespace: monitoring
  labels:
    release: monitoring
spec:
  selector:
    matchLabels:
      app.kubernetes.io/name: prometheus-operator
  endpoints:
    - port: http
      path: /metrics
      interval: 30s
```

### Диагностика саммониторинга

```bash
# 1. Проверка метрик Operator
kubectl exec -n monitoring prometheus-main-0 -- wget -qO- \
  http://localhost:9090/metrics | grep -E "prometheus_operator_reconcile|prometheus_config_last_reload"

# 2. Проверка количества активных серий
kubectl exec -n monitoring prometheus-main-0 -- wget -qO- \
  http://localhost:9090/api/v1/query?query=prometheus_tsdb_head_series | jq .

# 3. Проверка размера конфига
kubectl get secret prometheus-main -n monitoring \
  -o jsonpath='{.data.prometheus\.yaml\.gz}' | base64 -d | gunzip | wc -c

# 4. Проверка Remote Write лага
kubectl exec -n monitoring prometheus-main-0 -- wget -qO- \
  'http://localhost:9090/api/v1/query?query=prometheus_remote_storage_highest_timestamp_in_seconds - prometheus_remote_storage_queue_highest_sent_timestamp_seconds' | jq .

# 5. Проверка участников Alertmanager кластера
kubectl exec -n monitoring alertmanager-main-0 -c alertmanager -- \
  amtool cluster show
```

---

## Дополнительная информация

### Связанные файлы

| Файл | Содержание |
|:---|:---|
| [Концепции](./concepts.md) | Ключевые метрики Operator, архитектура |
| [Troubleshooting](./troubleshooting.md) | Диагностика сбоев reconciliation |
| [High Availability](./high_availability.md) | HA Prometheus, Alertmanager Gossip |

### Частые ошибки на собеседованиях

1. **"Мониторинг мониторинга — избыточность"** — Нет. Если Prometheus упал, вы не увидите алерты о других сбоях. Self-monitoring — критически важная практика.
2. **"reconcile_errors > 0 = Operator сломан"** — Нет. Кратковременные ошибки reconciliation нормальны (например, при обновлении CRD). Критично, если ошибки длятся >5 минут.
3. **"config-reloader перезагружает Prometheus при каждом изменении"** — Нет. config-reloader отслеживает только примонтированные Secret/ConfigMap. Если Secret не изменился — reload не происходит.
