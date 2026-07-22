# Интеграция с системами эскалации — Incident Management

## Определения

**Системы эскалации (Escalation Systems)** — платформы для управления инцидентами (PagerDuty, Opsgenie, Splunk On-Call), обеспечивающие автоматизацию дежурств (on-call), многоуровневое оповещение и контроль жизненного цикла критических событий.

**Incident Response & Management (IRM)** — комплексный подход к обработке инцидентов, включающий обнаружение, оповещение, совместную работу инженеров и последующий анализ (post-mortem).

**Grafana OnCall** — решение от Grafana Labs для управления инцидентами. 
*   **OnCall Cloud:** Активно развиваемая SaaS-версия в составе Grafana Cloud IRM.
*   **OnCall OSS:** Open-source версия, официально **архивирована 24 марта 2026 года**. Cloud Connection деактивирован, функции SMS и звонков в OSS-версии не поддерживаются.

## Базовые концепции

### Разделение ответственности

| Система | Сфера ответственности |
| :--- | :--- |
| **Grafana** | Мониторинг, оценка правил, генерация алерта, передача данных в IRM. |
| **IRM (PagerDuty/Opsgenie)** | Маршрутизация на основе графиков дежурств, эскалация при отсутствии квитирования (Acknowledge), группировка алертов в инциденты. |

### Сравнение систем управления инцидентами (2026)

| Критерий | PagerDuty | Opsgenie | GoAlert (OSS) | Grafana Cloud IRM |
| :--- | :--- | :--- | :--- | :--- |
| **Тип** | SaaS | SaaS | Самостоятельная установка | SaaS |
| **Сложность эскалации** | Экстремально высокая | Высокая | Средняя | Средняя |
| **Интеграция с Grafana** | Нативная (Events API v2) | Нативная | Webhook | Нативная + OnCall Plugin |
| **Поддержка** | Корпоративный стандарт | В составе Atlassian | Сообщество | Grafana Labs |
| **Статус 2026** | Лидер рынка | Стабильно | Рекомендованная замена OnCall OSS | Приоритет для Grafana |

### Механизм эскалации

Эскалация гарантирует, что инцидент не будет проигнорирован. Если первый инженер в графике не подтвердил получение алерта (Acknowledge) в течение `X` минут, система переходит на следующий уровень.

**Пример цепочки эскалации:**
1.  **Уровень 1 (0–5 мин):** Дежурный инженер (Push в приложении, Slack).
2.  **Уровень 2 (5–15 мин):** Дублирующий инженер (Голосовой звонок, SMS).
3.  **Уровень 3 (15+ мин):** Тимлид или дежурный администратор (Звонок).

## Практические сценарии

### Настройка PagerDuty через Provisioning

Для обеспечения безопасности используйте переменные окружения для хранения ключей интеграции.

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

### Настройка Opsgenie с приоритетами

Opsgenie позволяет динамически назначать приоритет инцидента на основе меток Grafana.

```yaml
# provisioning/alerting/contact-points-opsgenie.yaml
apiVersion: 1

contactPoints:
  - orgId: 1
    name: opsgenie-devops
    receivers:
      - uid: og-devops-receiver
        type: opsgenie
        settings:
          apiKey: ${OPSGENIE_API_KEY}
          apiURL: "https://api.opsgenie.com/v2/alerts"
          message: "[{{ .Status | upper }}] {{ .CommonLabels.alertname }}"
          # Приоритет P1 для critical, P3 для остальных
          priority: "{{ if eq .CommonLabels.severity \"critical\" }}P1{{ else }}P3{{ end }}"
          description: |
            Описание: {{ .CommonAnnotations.description }}
            Инстанс: {{ .CommonLabels.instance }}
            Дашборд: {{ .DashboardURL }}
          responders:
            - type: team
              name: DevOps-OnCall
```

### Маршрутизация многоуровневых уведомлений

Настройка политики уведомлений для разделения потоков между мессенджерами и системами эскалации.

```yaml
# provisioning/alerting/policies/escalation-routing.yaml
apiVersion: 1

policies:
  - orgId: 1
    receiver: telegram-default
    group_by: ["alertname", "cluster"]
    routes:
      # Критичные алерты — в PagerDuty (эскалация)
      - receiver: pagerduty-critical
        object_matchers:
          - ["severity", "=", "critical"]
        group_wait: 10s
        repeat_interval: 30m
      # Предупреждения — только в Opsgenie (без ночных звонков)
      - receiver: opsgenie-devops
        object_matchers:
          - ["severity", "=", "warning"]
        group_wait: 1m
        repeat_interval: 4h
```

## Безопасность и секреты

1.  **Интерполяция переменных:** Всегда используйте `${VARIABLE_NAME}` в конфигурации Grafana. Никогда не фиксируйте API-ключи в Git-репозиториях.
2.  **Принцип минимизации привилегий:** В PagerDuty/Opsgenie используйте "Integration Keys" или "API Keys" с ограниченными правами (только на создание алертов), а не глобальные ключи администратора.
3.  **Сетевая изоляция:** Если Grafana находится в закрытом контуре, убедитесь, что разрешен исходящий HTTPS-трафик к эндпоинтам `events.pagerduty.com` или `api.opsgenie.com`.

## Дополнительная информация

**См. также:**

- [Основные концепции Grafana Alerting](./concepts.md) — терминология и жизненный цикл оповещений.
- [Интеграция с Telegram](./telegram_integration.md) — настройка быстрых уведомлений.
- [Provisioning алертов](./provisioning.md) — декларативное управление ресурсами.
- [Best Practices: Алертинг](./best_practices.md) — рекомендации по снижению шума.
