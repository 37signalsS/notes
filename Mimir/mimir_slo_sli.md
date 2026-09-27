# Mimir: SLO/SLI для самого Mimir как сервиса

## 1. Определения

**SLI (Service Level Indicator)** — измеримый показатель качества сервиса. Для Mimir это доступность записи/чтения, задержка запросов, отсутствие потери данных.

**SLO (Service Level Objective)** — целевое значение SLI за определенный период. Например: "99.9% PromQL-запросов завершаются за < 2 секунды".

**Error Budget** — допустимое количество нарушений SLO. Если SLO = 99.9%, error budget = 0.1% (около 43 минут простоя в месяц).

**Зачем строить SLO для Mimir:** Mimir является критичной инфраструктурной платформой. Если Mimir недоступен, команда теряет видимость всех сервисов. SLO для Mimir позволяет объективно оценивать его надежность и планировать обновления.

## 2. Теоретический блок

### Ключевые SLI для Mimir

| SLI | Что измеряет | Формула |
|-----|-------------|---------|
| **Write Availability** | Доступность приема метрик | `1 - (отброшенные сэмплы / принятые сэмплы)` |
| **Read Availability** | Доступность PromQL-запросов | `1 - (ошибки запросов / все запросы)` |
| **Read Latency** | Задержка PromQL-запросов | `fraction_over_time(query_duration_seconds[5m])` |
| **Data Freshness** | Свежесть данных в Mimir | `(now - latest_sample_timestamp)` |
| **Ingestion Lag** | Задержка ingestion | `sum(mimir_ingester_tsdb_head_max_time - time()) by (instance)` |

### Рекомендуемые SLO

| SLO | Целевое значение | Error Budget (30 дней) |
|-----|-----------------|----------------------|
| Write Availability | 99.99% | 4.3 минуты |
| Read Availability | 99.9% | 43 минуты |
| Read Latency (p99) | < 2 секунды | — |
| Data Freshness | < 2 минуты | — |

## 3. Практический блок

### SLI: Write Availability

```yaml
# Запись: доля принятых сэмплов от отправленных
groups:
  - name: mimir_write_sli
    interval: 60s
    rules:
      # Общее количество принятых сэмплов
      - record: mimir:write:accepted_samples:rate5m
        expr: sum(rate(mimir_distributor_received_samples_total[5m])) by (user)

      # Количество отброшенных сэмплов
      - record: mimir:write:discarded_samples:rate5m
        expr: sum(rate(mimir_distributor_discarded_samples_total[5m])) by (user)

      # SLI: доля успешной записи
      - record: mimir:write:sli:ratio
        expr: |
          1 - (
            mimir:write:discarded_samples:rate5m
            /
            mimir:write:accepted_samples:rate5m
          )
```

### SLI: Read Availability

```yaml
groups:
  - name: mimir_read_sli
    interval: 60s
    rules:
      # Количество успешных запросов
      - record: mimir:read:successful_queries:rate5m
        expr: sum(rate(mimir_query_frontend_queries_total{status="success"}[5m]))

      # Количество ошибочных запросов
      - record: mimir:read:failed_queries:rate5m
        expr: sum(rate(mimir_query_frontend_queries_total{status="fail"}[5m]))

      # SLI: доля успешного чтения
      - record: mimir:read:sli:ratio
        expr: |
          mimir:read:successful_queries:rate5m
          /
          (mimir:read:successful_queries:rate5m + mimir:read:failed_queries:rate5m)
```

### SLI: Read Latency

```yaml
groups:
  - name: mimir_read_latency_sli
    interval: 60s
    rules:
      # P99 задержка запросов
      - record: mimir:read:latency_p99
        expr: histogram_quantile(0.99, sum(rate(mimir_query_frontend_duration_seconds_bucket[5m])) by (le))

      # P95 задержка запросов
      - record: mimir:read:latency_p95
        expr: histogram_quantile(0.95, sum(rate(mimir_query_frontend_duration_seconds_bucket[5m])) by (le))
```

### SLI: Data Freshness

```yaml
groups:
  - name: mimir_freshness_sli
    interval: 60s
    rules:
      # Задержка данных от ingestion до доступности
      - record: mimir:data:freshness:seconds
        expr: time() - max(mimir_ingester_tsdb_head_max_time) by (instance)
```

### Error Budget: Burn Rate алерты

```yaml
groups:
  - name: mimir_slo_alerts
    rules:
      # Error budget для write availability (SLO 99.99%)
      - record: mimir:write:error_budget:burn_rate_1h
        expr: |
          1 - mimir:write:sli:ratio
          / (1 - 0.9999)

      # Алерт: высокий burn rate (критичный)
      - alert: MimirWriteErrorBudgetBurnRateHigh
        expr: mimir:write:error_budget:burn_rate_1h > 14.4
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "Mimir: быстрое сжигание error budget для записи"
          description: "Скорость сжигания бюджета ошибок > 14.4x. При таком темпе бюджет исчерпается через {{ $value | humanizeDuration }}"
          runbook_url: "https://wiki.example.com/runbooks/mimir-error-budget"

      # Алерт: медленное сжигание (warning)
      - alert: MimirWriteErrorBudgetBurnRateLow
        expr: mimir:write:error_budget:burn_rate_1h > 3
        for: 15m
        labels:
          severity: warning
        annotations:
          summary: "Mimir: медленное сжигание error budget для записи"

      # Error budget для read availability (SLO 99.9%)
      - alert: MimirReadErrorBudgetBurnRateHigh
        expr: |
          (1 - mimir:read:sli:ratio) / (1 - 0.999) > 14.4
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "Mimir: быстрое сжигание error budget для чтения"
```

### Дашборд для SLO Mimir

```json
{
  "panels": [
    {
      "title": "Write SLI (Availability)",
      "type": "timeseries",
      "targets": [
        {
          "expr": "mimir:write:sli:ratio",
          "legendFormat": "{{ user }}"
        }
      ],
      "fieldConfig": {
        "defaults": {
          "min": 0.99,
          "max": 1,
          "thresholds": {
            "steps": [
              { "value": 0.9999, "color": "green" },
              { "value": 0.999, "color": "yellow" },
              { "value": 0.99, "color": "red" }
            ]
          }
        }
      }
    },
    {
      "title": "Read Latency P99",
      "type": "timeseries",
      "targets": [
        {
          "expr": "mimir:read:latency_p99",
          "legendFormat": "P99"
        }
      ]
    },
    {
      "title": "Write Error Budget Remaining",
      "type": "gauge",
      "targets": [
        {
          "expr": "100 - (mimir:write:error_budget:burn_rate_1h * 100 / 30 * 24 * 60)"
        }
      ]
    }
  ]
}
```

## 4. Дополнительная информация

### См. также
- [Mimir: Обзор](./mimir_overview.md) — метрики мониторинга Mimir
- [Recording Rules](./mimir_recording_rules.md) — recording rules для SLI-метрик
- [SRE Concepts](../Concepts/sre_concepts_main.md) — общие принципы SLI/SLO/Error Budget
- [Мониторинг и алертинг](../Concepts/Observability_and_Monitoring/monitoring_alerting_recommendations.md) — Burn Rate, multi-window алерты
- [Grafana Alerting Best Practices](../Grafana/alerting/best_practices.md) — методология алертинга

### Официальные ресурсы
- **[Google SRE Workbook](https://sre.google/workbook/implementing-slos/)** — практическое руководство по SLO
- **[Mimir Monitoring](https://grafana.com/docs/mimir/latest/manage/monitoring/)** — метрики самого Mimir
