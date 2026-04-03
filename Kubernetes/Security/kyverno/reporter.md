# Policy Reporter

## Определения

**Policy Reporter** — отдельное приложение для просмотра и управления отчетами Kyverno. Предоставляет Web UI, метрики для Prometheus/Grafana, REST API и уведомления. Официальный репозиторий: <https://github.com/kyverno/policy-reporter>

---

## Базовые концепции

### Возможности Policy Reporter

| Компонент | Назначение |
|-----------|------------|
| **Web UI** | Графический интерфейс для просмотра отчетов, группировка по категориям, фильтрация |
| **Metrics** | Генерация метрик для Prometheus/Grafana |
| **REST API** | Встроенный API для интеграции с внешними системами |
| **Централизованный сбор** | Агрегация отчетов с нескольких namespace в одно место |
| **Уведомления** | Отправка уведомлений в Discord, Slack, Telegram, Teams |
| **Экспорт отчетов** | Выгрузка отчетов в различных форматах |

### Архитектура

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│   Kyverno       │────▶│  Policy Reporter │────▶│   Prometheus    │
│  (Reports)      │     │     (Core)       │     │   (Metrics)     │
└─────────────────┘     └──────────────────┘     └─────────────────┘
                               │
                               ├────▶ Web UI (Dashboard)
                               │
                               ├────▶ REST API
                               │
                               └────▶ Notifications (Slack/Telegram)
```

---

## Практические сценарии

### Установка через Helm

```bash
# Добавление репозитория
helm repo add policy-reporter https://kyverno.github.io/policy-reporter
helm repo update

# Установка с базовыми настройками
helm install policy-reporter policy-reporter/policy-reporter \
  --namespace policy-reporter \
  --create-namespace \
  --set ui.enabled=true \
  --set ui.plugins.kyverno=true \
  --set metrics.enabled=true \
  --set prometheus.enabled=true
```

### Расширенная конфигурация

```yaml
# values.yaml
metrics:
  enabled: true

ui:
  enabled: true
  plugins:
    kyverno: true
    webhook: true

api:
  enabled: true
  port: 8080

# Интеграция с Prometheus
prometheus:
  enabled: true
  port: 9080

# Уведомления в Slack
slack:
  enabled: true
  webhook: "https://hooks.slack.com/services/XXX/YYY/ZZZ"
  minimumPriority: "high"

# Уведомления в Telegram
telegram:
  enabled: true
  token: "BOT_TOKEN"
  chatID: "CHAT_ID"
  minimumPriority: "critical"

# Filter по namespace
filter:
  namespaces:
    include: ["default", "production", "staging"]
    exclude: ["kube-system", "kube-public"]
```

### Проверка установки

```bash
# Проверка подов
kubectl get pods -n policy-reporter

# Ожидаемый вывод:
# NAME                                READY   STATUS    RESTARTS   AGE
# policy-reporter-5f8c9d7b9c-abc12    1/1     Running   0          5m
# policy-reporter-ui-6d9f8e7c8d-def34 1/1     Running   0          5m

# Проверка сервиса
kubectl get svc -n policy-reporter

# Доступ к Web UI (port-forward)
kubectl port-forward svc/policy-reporter-ui -n policy-reporter 8080:80
```

### Доступные метрики

Метрики экспортируются в формате Prometheus. Детальная структура метрик описана в [Policy Reports](./reports.md).

Основные метрики:

```prometheus
# Общее количество результатов
policy_report_result_total{result="fail", policy="require-run-as-non-root"}

# Сводка по namespace
policy_report_summary_fail{namespace="default"}
policy_report_summary_pass{namespace="default"}
policy_report_summary_warn{namespace="default"}
policy_report_summary_error{namespace="default"}
policy_report_summary_skip{namespace="default"}

# Изменения во времени
rate(policy_report_result_total{result="fail"}[5m])
increase(policy_report_result_total{result="fail"}[1h])

# По категориям
policy_report_result_total{category="security", result="fail"}
policy_report_result_total{category="best-practices", result="fail"}
```

### Настройка уведомлений

#### Slack

```yaml
slack:
  enabled: true
  webhook: "https://hooks.slack.com/services/XXX/YYY/ZZZ"
  minimumPriority: "high"
  channels:
    - "#security-alerts"
    - "#platform-team"
```

#### Telegram

```yaml
telegram:
  enabled: true
  token: "BOT_TOKEN"
  chatID: "CHAT_ID"
  minimumPriority: "critical"
```

#### Webhook (универсальный)

```yaml
webhook:
  enabled: true
  endpoint: "https://your-api.example.com/alerts"
  minimumPriority: "high"
  headers:
    Authorization: "Bearer YOUR_TOKEN"
```

### REST API

```bash
# Получить все Policy Reports
curl http://localhost:8080/api/v1/policy-reports

# Получить отчеты с нарушениями
curl http://localhost:8080/api/v1/policy-reports?result=fail

# Получить отчеты по namespace
curl http://localhost:8080/api/v1/policy-reports?namespace=default

# Получить сводку
curl http://localhost:8080/api/v1/summary
```

---

## Дополнительная информация

### Производительность

| Параметр | Рекомендация |
|----------|--------------|
| Количество namespace | До 100-200 без проблем |
| Частота обновления | По умолчанию 15 минут |
| Ресурсы | 100-200 MB RAM, 0.1-0.3 CPU |

### Troubleshooting

| Проблема | Решение |
|----------|---------|
| UI не доступен | Проверить `kubectl get pods -n policy-reporter` |
| Метрики не собираются | Проверить `prometheus.enabled: true` |
| Уведомления не приходят | Проверить webhook URL и права доступа |
| Отчеты не обновляются | Проверить права на чтение Policy Reports |

### Grafana Dashboard

Официальные dashboard доступны в [репозитории Policy Reporter](https://github.com/kyverno/policy-reporter/tree/main/charts/policy-reporter/files/grafana). Импорт через ConfigMap:

```bash
kubectl create configmap grafana-dashboard \
  --from-file=kyverno-policy-reporter.json \
  -n grafana
```
