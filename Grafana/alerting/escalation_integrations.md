# Интеграция с системами эскалации — Incident Management

## Определения

**Системы эскалации (Escalation Systems)** — платформы для управления инцидентами (PagerDuty, Opsgenie, Splunk On-Call, GoAlert), обеспечивающие автоматизацию дежурств (on-call), многоуровневое оповещение и контроль жизненного цикла критических событий.

**Incident Response & Management (IRM)** — комплексный подход к обработке инцидентов, включающий обнаружение, оповещение, совместную работу инженеров и последующий анализ (post-mortem).

**Grafana Cloud IRM** — современный стек инструментов Grafana Labs для управления инцидентами, включающий:
*   **Grafana OnCall:** Централизованное управление дежурствами, эскалациями и расписаниями (приоритетное решение в 2026 году).
*   **Grafana Incident:** Инструмент для координации действий во время активного сбоя (автоматическое создание Slack-каналов, Zoom-конференций и ведение таймлайна инцидента).

**Grafana OnCall OSS** — Open-source версия, официально **архивирована 24 марта 2026 года**. Рекомендуется миграция на Grafana Cloud IRM или использование GoAlert.

## Базовые концепции

### Разделение ответственности

| Система | Сфера ответственности |
| :--- | :--- |
| **Grafana** | Мониторинг, оценка правил, генерация алерта, обогащение контекстом (Runbooks, Dashboard links). |
| **IRM (PagerDuty/OnCall)** | Маршрутизация по графикам дежурств, эскалация при отсутствии реакции, агрегация алертов в инциденты. |

### Сравнение систем управления инцидентами (2026)

| Критерий | PagerDuty | Opsgenie | Splunk On-Call | GoAlert (OSS) | Grafana Cloud IRM |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Тип** | SaaS | SaaS | SaaS | Самостоятельная | SaaS |
| **Эскалация** | Экстремальная | Высокая | Высокая | Средняя | Средняя |
| **Интеграция** | Нативная | Нативная | VictorOps | Webhook | Нативная |
| **Статус 2026** | Лидер рынка | Стабильно | Enterprise | Рекомендованный OSS | Приоритет Grafana |

### Жизненный цикл инцидента

1.  **Обнаружение (Detect):** Grafana фиксирует нарушение порогового значения и отправляет сигнал в IRM-систему.
2.  **Оповещение (Notify):** IRM определяет текущего дежурного согласно графику и отправляет уведомление (Push, SMS, звонок).
3.  **Квитирование (Acknowledge):** Инженер подтверждает получение через приложение или мессенджер. Таймер эскалации останавливается.
4.  **Анализ и исправление (Fix):** Инженер использует ссылки на Runbook и Дашборд, переданные в теле алерта, для диагностики.
5.  **Разрешение (Resolve):** Grafana отправляет сигнал восстановления (`[RESOLVED]`), IRM автоматически закрывает инцидент.

## Практические сценарии

### Настройка PagerDuty через провиженинг

```yaml
# provisioning/alerting/contact-points-pagerduty.yaml
apiVersion: 1

contactPoints:
  - orgId: 1
    name: pagerduty-critical
    receivers:
      - uid: pd-critical-receiver
        type: pagerduty
        settings:
          # Ключ интеграции из PagerDuty (Events API v2)
          integrationKey: ${PAGERDUTY_INTEGRATION_KEY}
          severity: critical
          class: infrastructure
          component: kubernetes-cluster
          group: backend
          summary: "Критический сбой: {{ .CommonAnnotations.summary }}"
          # Автоматическое разрешение инцидента в PD при восстановлении в Grafana
          autoResolve: true
```

### Настройка Splunk On-Call (VictorOps)

Для интеграции используется тип `victorops`. Routing Key позволяет направлять алерты конкретным командам.

```yaml
# provisioning/alerting/contact-points-victorops.yaml
apiVersion: 1

contactPoints:
  - orgId: 1
    name: splunk-oncall-devops
    receivers:
      - uid: vo-devops-receiver
        type: victorops
        settings:
          url: "https://alert.victorops.com/integrations/generic/20131114/alert/${VICTOROPS_API_KEY}/devops"
          autoResolve: true
```

### Настройка GoAlert через Webhook

GoAlert — основная open-source альтернатива для управления дежурствами в 2026 году.

```yaml
# provisioning/alerting/contact-points-goalert.yaml
apiVersion: 1

contactPoints:
  - orgId: 1
    name: goalert-infra
    receivers:
      - uid: goalert-receiver
        type: webhook
        settings:
          url: "https://goalert.example.com/api/v2/webhooks/grafana?token=${GOALERT_TOKEN}"
          httpMethod: POST
```

### Обогащение алертов контекстом (Enrichment)

Для минимизации времени реакции (MTTR) алерты должны содержать ссылки на документацию и инструменты диагностики.

```yaml
# Пример аннотаций в YAML-описании правила (Rule)
annotations:
  summary: "Высокая задержка API на {{ .Labels.instance }}"
  runbook_url: "https://wiki.example.com/runbooks/api-latency"
  dashboard_url: "https://grafana.example.com/d/api-overview?var-cluster={{ .Labels.cluster }}"
```

### Периоды тишины (Mute Timings)

Позволяют подавлять уведомления и эскалацию в нерабочее время (для некритичных систем) или во время плановых работ.

```yaml
# provisioning/alerting/mute-timings.yaml
apiVersion: 1

muteTimings:
  - name: maintenance-weekends
    timeIntervals:
      - weekdays: ["saturday", "sunday"]
        times:
          - start: "00:00"
            end: "23:59"
```

## Безопасность и секреты

1.  **Интерполяция переменных:** Всегда используйте `${VARIABLE_NAME}` в конфигурации Grafana. Никогда не фиксируйте API-ключи в Git-репозиториях.
2.  **Принцип минимизации привилегий:** В PagerDuty/Opsgenie используйте ключи с ограниченными правами (только на создание событий), а не глобальные токены администратора.
3.  **Сетевая изоляция:** Убедитесь, что разрешен исходящий HTTPS-трафик к эндпоинтам `events.pagerduty.com`, `api.opsgenie.com` или `alert.victorops.com`.

## Дополнительная информация

**См. также:**

- [Обзор Grafana Alerting](./concepts.md) — терминология и жизненный цикл оповещений.
- [Интеграция Grafana с Telegram](./telegram-integration.md) — настройка уведомлений для быстрой реакции.
- [Декларативное управление оповещениями](./provisioning.md) — управление ресурсами через YAML.
- [Лучшие практики алертинга](./best_practices.md) — рекомендации по снижению шума.
