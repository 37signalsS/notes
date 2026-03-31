# Интеграция Grafana с Telegram

## Определения

**Telegram-интеграция** — нативный контак-пойнт Grafana для отправки уведомлений об алертах в Telegram-чаты и каналы.

**Текущая версия (февраль 2026):** Grafana 12.x (требуется 9.0+)

## Базовые концепции

### Преимущества Telegram как канала уведомлений

| Преимущество | Описание |
| :--- | :--- |
| **Мобильность** | Push-уведомления на смартфоне |
| **Форматирование** | Поддержка Markdown, эмодзи, ссылок |
| **Группировка** | Чаты по командам/проектам |
| **Надёжность** | Высокая доступность сервиса |
| **Простота** | Быстрая настройка через бота |

### Требования

| Компонент | Требование |
| :--- | :--- |
| **Grafana** | Версия 9.0+ (нативная поддержка) |
| **Telegram Bot** | Токен от @BotFather |
| **Chat ID** | ID чата/канала (получается через бота) |
| **Доступность API** | `api.telegram.org` должен быть доступен из сети Grafana |

> **Важно:** В версиях Grafana < 9.0 используйте webhook с Telegram Bot API.

### Получение реквизитов

**Шаг 1: Создание бота**

1. В Telegram найдите `@BotFather`
2. Отправьте команду `/newbot`
3. Укажите имя и username бота
4. Скопируйте полученный **токен** (формат: `1234567890:ABCdefGHIjklMNOpqrsTUVwxyz`)

**Шаг 2: Получение Chat ID**

1. Добавьте бота в чат/канал
2. Для канала: сделайте бота администратором
3. Отправьте сообщение в чат
4. Выполните запрос к API:

```bash
curl "https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getUpdates"
```

5. Найдите в ответе `"chat":{"id":<CHAT_ID>}`
6. Для каналов ID отрицательный (например, `-1001234567890`)

## Практические сценарии

### Базовая конфигурация контак-пойнта

```yaml
# provisioning/alerting/contactpoints/telegram.yaml
apiVersion: 1

contactPoints:
  - orgId: 1
    name: team-devops-telegram
    receivers:
      - uid: telegram-receiver
        type: telegram
        settings:
          botToken: "<YOUR_BOT_TOKEN>"
          chatId: "<YOUR_CHAT_ID>"
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

---

### Расширенный шаблон с форматированием

```yaml
contactPoints:
  - orgId: 1
    name: telegram-critical
    receivers:
      - uid: telegram-critical-receiver
        type: telegram
        settings:
          botToken: "<BOT_TOKEN>"
          chatId: "<CHAT_ID>"
          message: |
            {{ define "telegram.critical.message" }}
            🔴 *CRITICAL ALERT*

            *{{ .CommonAnnotations.summary }}*

            {{ if .CommonAnnotations.description }}
            _{{ .CommonAnnotations.description }}_
            {{ end }}

            ━━━━━━━━━━━━━━
            *Информация:*
            • Алерт: `{{ .CommonLabels.alertname }}`
            • Сервис: `{{ .CommonLabels.service }}`
            • Окружение: `{{ .CommonLabels.environment }}`
            • Инстанс: `{{ .CommonLabels.instance }}`
            • Критичность: `{{ .CommonLabels.severity }}`

            *Время:*
            • Начало: {{ .StartsAt.Format "02.01.2006 15:04 MSK" }}
            • Длительность: {{ .Duration }}

            {{ if .CommonAnnotations.runbook }}
            *📖 Runbook:* {{ .CommonAnnotations.runbook }}
            {{ end }}

            {{ if .CommonAnnotations.dashboard }}
            *📊 Dashboard:* {{ .CommonAnnotations.dashboard }}
            {{ end }}

            [🔗 Открыть в Grafana]({{ .ExternalURL }})
            {{ end }}
```

---

### Шаблон для warning-алертов

```yaml
contactPoints:
  - orgId: 1
    name: telegram-warning
    receivers:
      - uid: telegram-warning-receiver
        type: telegram
        settings:
          botToken: "<BOT_TOKEN>"
          chatId: "<CHAT_ID>"
          message: |
            {{ define "telegram.warning.message" }}
            🟡 *WARNING*

            {{ .CommonAnnotations.summary }}

            *Значение:* {{ $value }}
            *Время:* {{ .StartsAt.Format "15:04 02.01" }}

            [Grafana]({{ .ExternalURL }})
            {{ end }}
```

---

### Политики уведомлений для Telegram

```yaml
# provisioning/alerting/policies/telegram-routing.yaml
apiVersion: 1

policies:
  - orgId: 1
    receiver: telegram-default
    group_by: ['alertname', 'namespace', 'service']
    group_wait: 30s
    group_interval: 5m
    repeat_interval: 4h
    routes:
      # Критичные алерты — немедленно
      - receiver: telegram-critical
        object_matchers:
          - ['severity', '=', 'critical']
        group_wait: 10s
        group_interval: 1m
        repeat_interval: 1h
      # Warning — с задержкой
      - receiver: telegram-warning
        object_matchers:
          - ['severity', '=', 'warning']
        group_wait: 1m
        group_interval: 10m
        repeat_interval: 4h
      # Info — только днём
      - receiver: telegram-info
        object_matchers:
          - ['severity', '=', 'info']
        group_wait: 5m
        repeat_interval: 24h
        active_time_intervals:
          - business-hours
```

**Параметры маршрутизации:**
- **`group_wait`:** Задержка перед первой отправкой (критичные — 10s, warning — 1m)
- **`group_interval`:** Интервал между группами уведомлений
- **`repeat_interval`:** Интервал повторных уведомлений
- **`object_matchers`:** Селекторы маршрутизации по меткам

---

### Несколько получателей (команды)

```yaml
contactPoints:
  # Команда Backend
  - orgId: 1
    name: telegram-backend
    receivers:
      - uid: telegram-backend-receiver
        type: telegram
        settings:
          botToken: "<BACKEND_BOT_TOKEN>"
          chatId: "<BACKEND_CHAT_ID>"

  # Команда Frontend
  - orgId: 1
    name: telegram-frontend
    receivers:
      - uid: telegram-frontend-receiver
        type: telegram
        settings:
          botToken: "<FRONTEND_BOT_TOKEN>"
          chatId: "<FRONTEND_CHAT_ID>"

  # Дежурные
  - orgId: 1
    name: telegram-oncall
    receivers:
      - uid: telegram-oncall-receiver
        type: telegram
        settings:
          botToken: "<ONCALL_BOT_TOKEN>"
          chatId: "<ONCALL_CHAT_ID>"

policies:
  - orgId: 1
    receiver: telegram-oncall
    group_by: ['alertname', 'service']
    routes:
      - receiver: telegram-backend
        object_matchers:
          - ['team', '=', 'backend']
      - receiver: telegram-frontend
        object_matchers:
          - ['team', '=', 'frontend']
```

---

### Troubleshooting

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| Уведомления не приходят | Неверный токен | Проверьте токен в @BotFather |
| Уведомления не приходят | Бот не в чате | Добавьте бота в чат/канал |
| Уведомления не приходят | Бот не администратор | Для каналов сделайте бота администратором |
| Ошибка API | `api.telegram.org` недоступен | Проверьте сетевую связность |
| Пустые сообщения | Ошибка в шаблоне | Проверьте синтаксис Go-шаблонов |
| Неверный Chat ID | ID найден неправильно | Используйте `getUpdates` для проверки |

## Дополнительная информация

**Связанные темы:**

- [Provisioning алертов](./provisioning.md) — структура контакт-пойнтов и политик
- [Основные концепции Grafana Alerting](./concepts.md) — дерево маршрутизации, `group_by`, `group_wait`
- [Интеграция с системами эскалации](./escalation_integrations.md) — PagerDuty, Opsgenie
- [Best practices](./best_practices.md) — рекомендации по настройке алертинга
