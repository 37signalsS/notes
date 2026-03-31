# Интеграция с системами эскалации

## Определения

**Системы эскалации** — специализированные платформы (PagerDuty, Opsgenie) для управления инцидентами: дежурства, графики, эскалация, трекирование.

**Grafana OnCall** — собственное решение Grafana для управления дежурствами и эскалациями.

**Текущая версия (февраль 2026):** Grafana 12.x

> **Важно:** Grafana OnCall для self-hosted не обновляется с весны 2026. Рекомендуется использовать PagerDuty или Opsgenie.

## Базовые концепции

### Разделение ответственности

| Система | Ответственность |
| :--- | :--- |
| **Grafana** | Обнаружение проблемы, отправка события |
| **Внешняя система** | Управление жизненным циклом инцидента: эскалация, графики дежурств, группировка, трекирование |

### Сравнение систем эскалации

| Критерий | PagerDuty | Opsgenie | Grafana OnCall |
| :--- | :--- | :--- | :--- |
| **Интеграция с Grafana** | Нативная (контакт-пойнт) | Нативная (контакт-пойнт) | Нативная (плагин) |
| **Графики дежурств** | Продвинутые | Продвинутые | Базовые |
| **Эскалация** | Многоуровневая | Многоуровневая | Базовая |
| **Трекирование инцидентов** | Полное | Полное | Ограниченное |
| **Стоимость** | Высокая | Средняя | Бесплатно (self-hosted) |
| **Статус** | Активно развивается | Активно развивается | ⚠️ Не обновляется |

### Механизм эскалации

**Пример:** Если дежурный инженер не реагирует на алерт в течение 5 минут, система автоматически передаёт его руководителю.

**Уровни эскалации:**

1. **Уровень 1:** Дежурный инженер (уведомление: push + email)
2. **Уровень 2:** Ведущий инженер (уведомление: SMS + звонок)
3. **Уровень 3:** Руководитель команды (уведомление: звонок)

## Практические сценарии

### Настройка PagerDuty в Grafana

**Шаг 1: Получение ключа интеграции**

1. В PagerDuty создайте сервис
2. Добавьте интеграцию типа «Grafana»
3. Скопируйте **Integration Key**

**Шаг 2: Создание контак-пойнта**

```yaml
# provisioning/alerting/contact-points-pagerduty.yaml
apiVersion: 1

contactPoints:
  - orgId: 1
    name: pagerduty-critical
    receivers:
      - uid: pagerduty-receiver
        type: pagerduty
        settings:
          integrationKey: "<YOUR_INTEGRATION_KEY>"
          severity: critical
          class: infrastructure
          component: grafana
          group: production
          summary: "{{ .CommonAnnotations.summary }}"
```

**Шаг 3: Настройка политики уведомлений**

```yaml
policies:
  - orgId: 1
    receiver: pagerduty-critical
    group_by: ["alertname", "service"]
    group_wait: 30s
    group_interval: 5m
    repeat_interval: 1h
    routes:
      - receiver: pagerduty-critical
        object_matchers:
          - ["severity", "=", "critical"]
```

### Настройка Opsgenie в Grafana

**Шаг 1: Получение API-ключа**

1. В Opsgenie создайте команду
2. Добавьте интеграцию типа «Grafana»
3. Скопируйте **API Key**

**Шаг 2: Создание контак-пойнта**

```yaml
# provisioning/alerting/contact-points-opsgenie.yaml
apiVersion: 1

contactPoints:
  - orgId: 1
    name: opsgenie-team
    receivers:
      - uid: opsgenie-receiver
        type: opsgenie
        settings:
          apiKey: "<YOUR_API_KEY>"
          apiURL: "https://api.opsgenie.com/v2/alerts"
          message: "{{ .CommonAnnotations.summary }}"
          description: "{{ .CommonAnnotations.description }}"
          priority: "{{ if eq .CommonLabels.severity \"critical\" }}P1{{ else }}P3{{ end }}"
          responders:
            - type: team
              name: DevOps
```

### Настройка многоуровневой эскалации

**Внешняя система (PagerDuty/Opsgenie):**

```yaml
# Эскалация настраивается в интерфейсе PagerDuty/Opsgenie
# Уровень 1: Дежурный (0–5 мин)
# Уровень 2: Ведущий (5–15 мин)
# Уровень 3: Руководитель (15+ мин)
```

**В Grafana (маршрутизация по критичности):**

```yaml
policies:
  - orgId: 1
    receiver: default
    group_by: ["alertname", "service"]
    routes:
      - receiver: pagerduty-critical
        object_matchers:
          - ["severity", "=", "critical"]
        group_wait: 10s
        repeat_interval: 1h
      - receiver: opsgenie-team
        object_matchers:
          - ["severity", "=", "warning"]
        group_wait: 1m
        repeat_interval: 4h
      - receiver: email-team
        object_matchers:
          - ["severity", "=", "info"]
        group_wait: 5m
        repeat_interval: 24h
```

### Шаблон сообщения для PagerDuty

```yaml
annotations:
  summary: "Critical: {{ .CommonLabels.alertname }} on {{ .CommonLabels.instance }}"
  description: |
    {{ .CommonAnnotations.description }}
    
    Метки:
    - Service: {{ .CommonLabels.service }}
    - Environment: {{ .CommonLabels.environment }}
    - Severity: {{ .CommonLabels.severity }}
    
    [Открыть в Grafana]({{ .ExternalURL }})
  runbook: "https://wiki.example.com/runbooks/{{ .CommonLabels.alertname }}"
```

## Дополнительная информация

**Связанные темы:**

- [Основные концепции Grafana Alerting](./concepts.md) — контак-пойнты, политики уведомлений
- [Интеграция с Telegram](./telegram_integration.md) — настройка Telegram-уведомлений
- [Provisioning алертов](./provisioning.md) — настройка через YAML
- [Best practices](./best_practices.md) — практические нюансы алертинга
- [Grafana overview](../grafana_overview.md) — обзор возможностей Grafana
