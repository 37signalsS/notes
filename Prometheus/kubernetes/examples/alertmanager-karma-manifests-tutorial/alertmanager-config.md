# Конфигурация Alertmanager (ConfigMap)

Создадим `ConfigMap`, содержащий **шаблон** конфигурации `alertmanager.yml`. Вместо реальных секретов в нем используются переменные-заглушки (например, `##SMTP_USER##`), которые `init-container` заменит на значения из `Secret`.

**`alertmanager-config-template.yaml`**
```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: alertmanager-config-template
  namespace: monitoring
data:
  alertmanager.yml.tpl: |
    global:
      # Заменится на значения из секрета
      smtp_smarthost: 'smtp.example.com:587'
      smtp_from: '##SMTP_USER##'
      smtp_auth_username: '##SMTP_USER##'
      smtp_auth_password: '##SMTP_PASSWORD##'

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
        # Черная дыра для алертов без маршрута
        blackhole_configs:
          - {}

      - name: 'email-receiver'
        email_configs:
          - to: 'admin@example.com'
            headers:
              subject: 'K8s-Alert: {{ .GroupLabels.alertname }}'

      - name: 'telegram-receiver'
        telegram_configs:
          - bot_token: '##TELEGRAM_TOKEN##'
            chat_id: ##TELEGRAM_CHAT_ID##
            parse_mode: 'HTML' # Режим форматирования
            message: '{{ template "telegram.default.html" . }}'

    # Подключаем шаблоны для сообщений
    templates:
      - '/etc/alertmanager/templates/*.tmpl'

```

## Смотрите также

- [Шаблоны сообщений](./04-alertmanager-templates.md) — Go-шаблоны для форматирования
- [Alertmanager StatefulSet](./05-alertmanager-statefulset.md) — развертывание с init-container
