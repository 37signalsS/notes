# Интеграция с Telegram

Telegram — популярный канал для оперативных уведомлений благодаря мобильности и поддержке форматирования.

## Контакт-пойнт для Telegram

```yaml
# provisioning/alerting/contact-points-telegram.yaml
apiVersion: 1

contactPoints:
  - orgId: 1
    name: team-devops-telegram
    receivers:
      - uid: telegram-receiver
        type: telegram
        settings:
          botToken: "<YOUR_BOT_TOKEN>"  # Получите от @BotFather
          chatId: "<YOUR_CHAT_ID>"      # ID чата (канал или группа)
          message: |
            {{ define "telegram.default.message" }}
            🚨 *{{ .CommonAnnotations.summary }}*

            {{ if .CommonAnnotations.description }}
            {{ .CommonAnnotations.description }}
            {{ end }}

            *Детали:*
            - Алерт: {{ .CommonLabels.alertname }}
            - Сервис: {{ .CommonLabels.service }}
            - Критичность: {{ .CommonLabels.severity }}
            - Время: {{ .StartsAt.Format "2006-01-02 15:04:05" }}

            {{ if .CommonAnnotations.runbook }}
            *Runbook:* {{ .CommonAnnotations.runbook }}
            {{ end }}

            [Перейти в Grafana]({{ .ExternalURL }})
            {{ end }}
```

## Политики уведомлений для Telegram

```yaml
policies:
  - orgId: 1
    receiver: team-devops-telegram
    group_by: ["alertname", "namespace", "service"]
    group_wait: 30s
    group_interval: 5m
    repeat_interval: 4h
    routes:
      - receiver: team-devops-telegram
        object_matchers:
          - ["severity", "=", "critical"]
        group_wait: 10s  # Быстрая доставка для критичных алертов
        repeat_interval: 1h
      - receiver: team-devops-telegram
        object_matchers:
          - ["severity", "=", "warning"]
        group_wait: 1m
        repeat_interval: 4h
```

> **Важно:** Для работы Telegram-уведомлений требуется Grafana 9.0+. В более ранних версиях используйте webhook с Telegram Bot API.

---

**Связанные темы:**

* [Provisioning](./provisioning.md) — структура контакт-пойнтов и политик
* [Основные концепции](./concepts.md) — дерево маршрутизации, group_by, group_wait
* [Интеграция с системами эскалации](./escalation_integrations.md) — PagerDuty, Opsgenie
