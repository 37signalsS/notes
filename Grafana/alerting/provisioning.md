# Настройка оповещений через Provisioning

Это основной подход для реализации Infrastructure as Code.

## Пример правила

```yaml
# provisioning/alerting/api-alerts.yaml
apiVersion: 1
groups:
  - orgId: 1
    name: api-alerts
    folder: Production
    interval: 1m
    rules:
      - uid: api_error_rate_high
        title: API error rate > 5%
        condition: B # Условие, которое триггерит алерт
        for: 5m
        noDataState: NoData
        execErrState: Error
        labels:
          service: api
          severity: critical
        annotations:
          summary: Высокая доля ошибок API
          runbook: Проверьте логи и зависимые сервисы
        data:
          - refId: A # Запрос PromQL
            datasourceUid: prometheus_ds_uid
            model:
              expr: 'sum(rate(http_requests_total{job="api",status=~"5.."}[5m])) / sum(rate(http_requests_total{job="api"}[5m])) * 100'
              instant: false
              format: time_series
          - refId: B # Выражение Threshold
            datasourceUid: __expr__
            model:
              type: threshold
              conditions:
                - evaluator: { type: gt, params: [5] }
                  query: { params: [A] }
```

## Пример контакт-пойнтов и политик

```yaml
# provisioning/alerting/contact-points.yaml
apiVersion: 1

contactPoints:
  - orgId: 1
    name: team-devops-email
    receivers:
      - uid: team-devops-email-receiver
        type: email
        settings:
          addresses: devops@example.com

policies:
  - orgId: 1
    receiver: team-devops-email
    group_by: ["alertname", "service"]
    group_wait: 30s
    group_interval: 5m
    repeat_interval: 4h
    routes:
      - receiver: team-devops-email
        object_matchers:
          - ["severity", "=", "critical"]
```

---

**Связанные темы:**

* [Основные концепции](./concepts.md) — определения, состояния правил
* [Алерты для Kubernetes](./kubernetes_alerts.md) — примеры правил для K8s
* [Интеграция с Telegram](./telegram_integration.md) — настройка Telegram-уведомлений
* [Provisioning Grafana](../grafana_provisioning.md) — общее описание provisioning
