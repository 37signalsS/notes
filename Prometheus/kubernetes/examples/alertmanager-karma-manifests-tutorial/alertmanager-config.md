# Конфигурация Alertmanager: ConfigMap и маршрутизация

## Определения

**ConfigMap конфигурации Alertmanager** — ресурс Kubernetes, хранящий файл `alertmanager.yml`. Начиная с версии 0.27+, Alertmanager поддерживает прямое использование переменных окружения в конфигурационном файле, что позволяет избежать хранения чувствительных данных (паролей, токенов) в ConfigMap.

> **См. также:** [Полная конфигурация Alertmanager](../../alertmanager.md#конфигурация-alertmanageryml).

---

## Основные концепции

### Использование переменных окружения

В файле конфигурации вместо реальных значений используются плейсхолдеры в формате `${VARIABLE_NAME}`. Значения этих переменных передаются в под Alertmanager через Kubernetes Secret.

| Компонент | Роль |
| :--- | :--- |
| **ConfigMap** | Хранит структуру `alertmanager.yml` с ссылками на переменные. Безопасен для Git. |
| **Kubernetes Secret** | Содержит реальные токены и пароли. |
| **Alertmanager** | Считывает переменные окружения при запуске (требуется флаг `--config.expand-external-variables`). |

### Структура файла конфигурации

1.  **Global:** Глобальные настройки (SMTP-серверы, интервалы).
2.  **Route:** Дерево маршрутизации, определяющее, куда отправлять конкретные алерты.
3.  **Receivers:** Описание способов доставки (Telegram, Email, Webhooks).
4.  **Templates:** Пути к файлам визуального оформления уведомлений.

---

## Практические сценарии

### Манифест ConfigMap

Пример конфигурации с нативной поддержкой переменных окружения.

**`alertmanager-config.yaml`**

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: alertmanager-config
  namespace: monitoring
data:
  alertmanager.yml: |
    global:
      smtp_smarthost: 'smtp.example.com:587'
      smtp_from: '${SMTP_USER}'
      smtp_auth_username: '${SMTP_USER}'
      smtp_auth_password: '${SMTP_PASSWORD}'

    route:
      group_by: ['job']
      group_wait: 30s
      group_interval: 5m
      repeat_interval: 12h
      receiver: 'default-receiver'
      routes:
        - receiver: 'telegram-receiver'
          matchers:
            - severity =~ "critical|warning"
          continue: true
        - receiver: 'email-receiver'
          matchers:
            - severity =~ "critical|warning"

    receivers:
      - name: 'default-receiver'
        blackhole_configs:
          - {}

      - name: 'email-receiver'
        email_configs:
          - to: 'admin@example.com'
            send_resolved: true
            headers:
              subject: 'K8s-Alert: {{ .GroupLabels.alertname }}'

      - name: 'telegram-receiver'
        telegram_configs:
          - bot_token: '${TELEGRAM_TOKEN}'
            chat_id: ${TELEGRAM_CHAT_ID}
            parse_mode: 'HTML'
            message: '{{ template "telegram.default.html" . }}'

    templates:
      - '/etc/alertmanager/templates/*.tmpl'
```

### Логика маршрутизации

-   **Severity Match:** Алерты с уровнем `critical` или `warning` отправляются одновременно в Telegram и Email благодаря параметру `continue: true`.
-   **Fallback:** Все остальные алерты попадают в `default-receiver` (blackhole), что предотвращает спам неклассифицированными уведомлениями.

---

## Дополнительная информация

- **[Шаблоны сообщений](./alertmanager-templates.md)** — Go-шаблоны для форматирования.
- **[Манифест StatefulSet](./alertmanager-statefulset.md)** — настройка запуска Alertmanager.
- **[Секреты Kubernetes](./secrets.md)** — подготовка учетных данных.
- **[Reliability Scores](../../../../GEMINI.md)** — методология оценки достоверности (Score: 10).
