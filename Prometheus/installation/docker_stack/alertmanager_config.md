# Конфигурация Alertmanager

Создайте файл `monitoring/alertmanager/config.yml`:

```yaml
global:
  resolve_timeout: 5m
  smtp_smarthost: 'smtp.example.com:587' # Замените на ваш SMTP-сервер
  smtp_from: 'alertmanager@example.com' # Email отправителя
  smtp_auth_username: 'your-username' # Логин SMTP
  smtp_auth_password: 'your-password' # Пароль SMTP

route:
  receiver: 'default-receiver'
  group_by: ['alertname', 'cluster', 'service'] # Группировка схожих алертов
  group_wait: 30s
  group_interval: 5m
  repeat_interval: 4h

  routes:
    - receiver: 'telegram-notifications' # Пример: маршрутизация критических алертов в Telegram
      match:
        severity: 'critical'

receivers:
  - name: 'default-receiver'
    email_configs:
      - to: 'admin-team@example.com' # Email получателя
        send_resolved: true # Отправлять уведомление о разрешении алерта

  - name: 'telegram-notifications'
    webhook_configs:
      - url: 'http://your-telegram-bot-webhook-url/...' # URL для интеграции с Telegram
        send_resolved: true
```

* **`global`**: Глобальные настройки, например, для SMTP.
* **`route`**: Определяет маршрутизацию алертов. `group_by` позволяет группировать схожие алерты в одно уведомление.
* **`receivers`**: Описывает "получателей" — каналы отправки (email, webhook, Slack и т.д.).
