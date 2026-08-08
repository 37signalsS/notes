# Декларативное управление оповещениями — Provisioning

## Определения

**Provisioning (Провиженинг) алертов** — методология Infrastructure as Code (IaC), позволяющая декларативно описывать все компоненты системы оповещений Grafana (правила, контакт-пойнты, политики, шаблоны) через YAML-файлы. Это исключает ручную настройку через UI и обеспечивает воспроизводимость конфигурации в разных окружениях (Dev/Stage/Prod).

## Базовые концепции

### Структура директорий

Grafana сканирует директорию `/etc/grafana/provisioning/alerting/` при запуске. Стандартная структура в 2025 году:

```
/etc/grafana/provisioning/alerting/
├── rules/           # Alerting и Recording rules
├── contactpoints/   # Контакт-пойнты (каналы уведомлений)
├── policies/        # Политики уведомлений (маршрутизация)
├── mute_timings/    # Интервалы подавления (расписания)
└── templates/       # Go-шаблоны сообщений
```

**Важные нюансы:**
- **Hot Reload:** Изменения в YAML-файлах подхватываются Grafana "на лету" без перезагрузки сервиса (за исключением глобальных настроек в `grafana.ini`).
- **UID Consistency:** Всегда задавайте статичные `uid` для всех ресурсов. Это предотвращает создание дубликатов при пересоздании контейнеров и сохраняет историю в базе данных.
- **Интерполяция переменных:** Используйте `${MY_SECRET}` для токенов. Для этого в `grafana.ini` должна быть включена опция `enable_env_vars_interpolation = true`.

---

## Правила (Alerting и Recording Rules)

### Техническая структура правила (`data`)

Поле `data` представляет собой массив объектов, описывающих конвейер обработки данных.

| Поле | Описание |
| :--- | :--- |
| `refId` | Идентификатор шага (например, `A`, `B`, `C`). |
| `datasourceUid` | UID источника данных или `__expr__` для вычислительных шагов. |
| `model` | Объект с параметрами запроса или выражения. |

**Параметры `model` для запросов (Query):**
- `expr`: Строка запроса (PromQL, LogQL, SQL).
- `instant`: `true/false` (для Prometheus/Mimir).
- `format`: `time_series` или `table`.

**Параметры `model` для выражений (Expression):**
- `type`: `math` (математика), `reduce` (агрегация), `resample` (изменение окна), `threshold` (порог).
- `conditions`: Массив условий для типа `threshold`.

### Пример: Alerting Rule с конвейером выражений

```yaml
# provisioning/alerting/rules/app-alerts.yaml
apiVersion: 1
groups:
  - orgId: 1
    name: "Application Alerts"
    folder: "Production"
    interval: 1m
    rules:
      - uid: high_error_rate_api
        title: "High Error Rate API"
        condition: C
        for: 5m
        noDataState: NoData
        execErrState: Error
        labels:
          severity: critical
          team: backend
        annotations:
          summary: "Высокая доля ошибок на {{ $labels.instance }}"
          description: "Доля ошибок: {{ $values.B.Value }}%"
        data:
          - refId: A
            datasourceUid: prometheus_prod
            model:
              expr: "sum(rate(http_errors_total[5m]))"
              format: time_series
          - refId: B
            datasourceUid: "__expr__"
            model:
              type: reduce
              reducer: last
              expression: A
          - refId: C
            datasourceUid: "__expr__"
            model:
              type: math
              expression: "$B > 10"
```

### Пример: Recording Rule (Нативный провиженинг)

Recording Rules позволяют вычислять метрики на стороне Grafana и записывать их обратно в источник.

```yaml
      - uid: node_cpu_usage_avg
        title: "node:cpu_usage:avg5m"
        record:
          metric: "node:cpu_usage:avg5m"
        data:
          - refId: A
            datasourceUid: mimir_ds
            model:
              expr: "avg(rate(node_cpu_seconds_total[5m]))"
```

---

## Контакт-пойнты (Contact Points)

Декларативная настройка каналов уведомлений. В 2025 году поддерживаются расширенные настройки безопасности и форматирования.

### Настройка Webhook и Kafka

```yaml
# provisioning/alerting/contactpoints/receivers.yaml
apiVersion: 1
contactPoints:
  - orgId: 1
    name: "Internal-Webhook"
    receivers:
      - uid: cp_webhook_01
        type: webhook
        settings:
          url: "https://alerts.internal.net/api/receive"
          httpMethod: "POST"
          maxAlerts: 10
          authorization:
            type: "Bearer"
            credentials: ${WEBHOOK_TOKEN}
  - name: "Kafka-Topic"
    receivers:
      - uid: cp_kafka_01
        type: kafka
        settings:
          restProxyUrl: "http://kafka-rest:8082"
          topic: "monitoring-events"
          # Включение скриншота через встроенный Image Renderer
          uploadImage: true 
```

### Настройка Telegram и Slack

Для детальной настройки Telegram (создание бота, получение Chat ID, шаблонизация MarkdownV2) см. специализированное руководство:
- **[Интеграция с Telegram](./telegram-integration.md)** — основной SSoT по теме.

Пример настройки Slack (кратко):
```yaml
  - name: "Slack-Alerts"
    receivers:
      - uid: cp_slack_01
        type: slack
        settings:
          recipient: "#monitoring"
          token: ${SLACK_TOKEN}
```

---

## Политики уведомлений (Маршрутизация)

Политики определяют, как алерты распределяются по контакт-пойнтам с использованием **Label Matching**.

### Использование object_matchers

```yaml
# provisioning/alerting/policies/routing.yaml
apiVersion: 1
policies:
  - orgId: 1
    receiver: "default-receiver"
    group_by: ["alertname", "cluster"]
    group_wait: 30s
    group_interval: 5m
    repeat_interval: 4h
    routes:
      - receiver: "critical-oncall"
        object_matchers:
          - ["severity", "=", "critical"]  # Точное совпадение
          - ["env", "=~", "prod.*"]        # Регулярное выражение
        group_wait: 10s
        continue: true  # Продолжить поиск по другим веткам
```

---

## Взаимодействие с Kubernetes и AlertmanagerConfig

Важно разделять сферу ответственности при работе в Kubernetes:

1.  **AlertmanagerConfig (CRD):** Это ресурс Prometheus Operator. Он управляет конфигурацией *внешнего* Alertmanager (того, который идет в комплекте с kube-prometheus-stack).
2.  **Grafana Alerting Provisioning:** Управляет *внутренним* Alertmanager Grafana.

**Можно ли управлять AlertmanagerConfig через провиженинг Grafana?**
Нет. `AlertmanagerConfig` — это объект Kubernetes, он создается через манифесты `kubectl` или Helm. Grafana Provisioning работает только с внутренними файлами Grafana.

**Как их связать?**
Если вы используете `AlertmanagerConfig` для настройки внешнего Alertmanager, вы можете через провиженинг Grafana настроить **Data Source** (Prometheus), чтобы он отправлял свои алерты именно туда, или использовать внешний Alertmanager в качестве основного бэкенда для уведомлений в настройках Grafana Alerting.

---

## Интервалы подавления (Mute Timings)

```yaml
# provisioning/alerting/mute_timings/schedules.yaml
apiVersion: 1
muteTimes:
  - orgId: 1
    name: "Maintenance-Window"
    time_intervals:
      - weekdays: ["monday"]
        times:
          - start: "02:00"
            end: "04:00"
        location: "UTC"
```

## Дополнительная информация

**См. также:**

- [Основные концепции Grafana Alerting](./concepts.md) — архитектура конвейера выражений и HA.
- [Best practices по алертингу](./best_practices.md) — рекомендации по фильтрации шума.
- [Интеграция с Telegram](./telegram-integration.md) — подробная настройка ботов.
- [Общий провиженинг Grafana](../grafana_provisioning.md) — управление дашбордами и плагинами.
