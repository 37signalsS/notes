# Конфигурация Alertmanager (ConfigMap-шаблон)

## Определения

**ConfigMap-шаблон Alertmanager** — Kubernetes ConfigMap, содержащий шаблон `alertmanager.yml` с переменными-плейсхолдерами (`##SMTP_USER##`, `##TELEGRAM_TOKEN##`) вместо реальных секретов. Финальный конфиг генерируется init-container'ом, который подставляет значения из Kubernetes Secret.

> **См. также:** [Полная конфигурация Alertmanager](../../alertmanager.md#конфигурация-alertmanageryml)

## Основные концепции

### Паттерн безопасного управления конфигурацией

| Компонент | Роль |
|---|---|
| **ConfigMap (шаблон)** | Хранит `alertmanager.yml.tpl` с плейсхолдерами; безопасен для Git |
| **Kubernetes Secret** | Содержит реальные токены, пароли, bot_token |
| **Init Container** | Читает шаблон + Secret → генерирует финальный `alertmanager.yml` в `emptyDir` |
| **Основной контейнер** | Монтирует готовый конфиг из `emptyDir` |

> Паттерн описан в материале [Развёртывание Alertmanager в Kubernetes](../../alertmanager.md#развёртывание-в-kubernetes-через-манифесты)

### Структура шаблона alertmanager.yml.tpl

| Блок | Назначение |
|---|---|
| `global` | SMTP-параметры с плейсхолдерами (`##SMTP_USER##`, `##SMTP_PASSWORD##`) |
| `route` | Маршрутизация алертов по severity (`critical`, `warning`) |
| `receivers` | Получатели: email, Telegram, blackhole (для алертов без маршрута) |
| `templates` | Путь к Go-шаблонам сообщений (`/etc/alertmanager/templates/*.tmpl`) |

## Практические сценарии

### Манифест ConfigMap

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

### Логика маршрутизации

- **`severity =~ "critical|warning"`** → алерты идут в `telegram-receiver` **и** `email-receiver` (благодаря `continue: true` в первом маршруте)
- **Алерты без matching-меток** → попадают в `default-receiver` (blackhole, уведомления не отправляются)

## Дополнительная информация

- [Шаблоны сообщений](./alertmanager-templates.md) — Go-шаблоны для форматирования Telegram/email уведомлений
- [Alertmanager StatefulSet](./alertmanager-statefulset.md) — манифест StatefulSet с init-container для генерации конфига
- [Секреты Kubernetes](./secrets.md) — хранение токенов и паролей для подстановки в шаблон
