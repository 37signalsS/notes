# Интеграция Grafana с Telegram

## Определения

**Telegram-интеграция** — нативный контакт-пойнт Grafana для отправки уведомлений об оповещениях в чаты и каналы мессенджера Telegram.

**Текущая версия (февраль 2026):** Grafana 12.x (требуется версия 9.0 или выше)

## Базовые концепции

### Преимущества Telegram как канала уведомлений

| Преимущество | Описание |
| :--- | :--- |
| **Мобильность** | Push-уведомления на мобильных устройствах |
| **Форматирование** | Поддержка Markdown, ссылок и текстового выделения |
| **Группировка** | Возможность создания отдельных чатов для разных команд или проектов |
| **Надежность** | Высокая доступность сервиса обмена сообщениями |
| **Простота** | Быстрая настройка через бота без необходимости сложной инфраструктуры |

### Требования

| Компонент | Требование |
| :--- | :--- |
| **Grafana** | Версия 9.0 или выше (нативная поддержка) |
| **Telegram Bot** | Токен, полученный от @BotFather |
| **Chat ID** | Идентификатор чата или канала |
| **Доступность API** | API (Application Programming Interface) `api.telegram.org` должен быть доступен со стороны Grafana |

> **Важно:** В версиях Grafana ниже 9.0 следует использовать механизм Webhook для взаимодействия с Telegram Bot API.

### Получение реквизитов

**Шаг 1: Создание бота**

1. В Telegram найдите официальный аккаунт `@BotFather`
2. Отправьте команду `/newbot`
3. Укажите имя (display name) и уникальное имя пользователя (username) для бота
4. Скопируйте полученный **токен** (формат: `1234567890:ABCdefGHIjklMNOpqrsTUVwxyz`)

**Шаг 2: Получение Chat ID**

1. Добавьте созданного бота в целевой чат или канал
2. Для каналов: обязательно назначьте бота администратором
3. Отправьте любое сообщение в этот чат
4. Выполните запрос к API для получения истории обновлений:

```bash
curl "https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getUpdates"
```

1. Найдите в JSON-ответе объект `"chat":{"id":<CHAT_ID>}`
2. Обратите внимание: для каналов ID обычно начинается с префикса `-100` (например, `-1001234567890`)

## Практические сценарии

### Базовая конфигурация контакт-пойнта

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
            *{{ .CommonAnnotations.summary }}*

            {{ if .CommonAnnotations.description }}
            {{ .CommonAnnotations.description }}
            {{ end }}

            *Детали:*
            - Оповещение: {{ .CommonLabels.alertname }}
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
            *КРИТИЧЕСКОЕ ОПОВЕЩЕНИЕ*

            *{{ .CommonAnnotations.summary }}*

            {{ if .CommonAnnotations.description }}
            _{{ .CommonAnnotations.description }}_
            {{ end }}

            ------------------------------
            *Информация:*
            - Название: `{{ .CommonLabels.alertname }}`
            - Сервис: `{{ .CommonLabels.service }}`
            - Окружение: `{{ .CommonLabels.environment }}`
            - Инстанс: `{{ .CommonLabels.instance }}`
            - Критичность: `{{ .CommonLabels.severity }}`

            *Время:*
            - Начало: {{ .StartsAt.Format "02.01.2006 15:04 MSK" }}
            - Длительность: {{ .Duration }}

            {{ if .CommonAnnotations.runbook }}
            *Инструкция (Runbook):* {{ .CommonAnnotations.runbook }}
            {{ end }}

            {{ if .CommonAnnotations.dashboard }}
            *Дашборд:* {{ .CommonAnnotations.dashboard }}
            {{ end }}

            [Открыть в Grafana]({{ .ExternalURL }})
            {{ end }}
```

---

### Шаблон для предупреждающих оповещений (Warning)

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
            *ПРЕДУПРЕЖДЕНИЕ*

            {{ .CommonAnnotations.summary }}

            *Текущее значение:* {{ $value }}
            *Время:* {{ .StartsAt.Format "15:04 02.01" }}

            [Открыть в Grafana]({{ .ExternalURL }})
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
      # Критические оповещения — немедленно
      - receiver: telegram-critical
        object_matchers:
          - ['severity', '=', 'critical']
        group_wait: 10s
        group_interval: 1m
        repeat_interval: 1h
      # Предупреждения (Warning) — с задержкой
      - receiver: telegram-warning
        object_matchers:
          - ['severity', '=', 'warning']
        group_wait: 1m
        group_interval: 10m
        repeat_interval: 4h
      # Информационные сообщения — только в рабочее время
      - receiver: telegram-info
        object_matchers:
          - ['severity', '=', 'info']
        group_wait: 5m
        repeat_interval: 24h
        active_time_intervals:
          - business-hours
```

**Основные параметры маршрутизации:**

- **`group_wait`**: Начальная задержка перед отправкой первого уведомления в группе
- **`group_interval`**: Интервал ожидания перед отправкой уведомлений о новых оповещениях для уже существующей группы
- **`repeat_interval`**: Интервал повторной отправки уведомления, если проблема не была устранена
- **`object_matchers`**: Правила сопоставления меток для выбора маршрута

---

### Диагностика и решение проблем

| Проблема | Вероятная причина | Решение |
| :--- | :--- | :--- |
| Уведомления не доставляются | Некорректный токен бота | Проверьте точность токена в @BotFather |
| Бот не отправляет сообщения | Бот не добавлен в чат или канал | Добавьте бота в целевой чат или канал |
| Бот не пишет в канал | Отсутствуют права администратора | Назначьте бота администратором канала с правом публикации сообщений |
| Ошибка соединения с API | Ограничение доступа к `api.telegram.org` | Проверьте сетевые настройки и доступность внешних ресурсов |
| Сообщения приходят пустыми | Ошибка в синтаксисе шаблона Go | Проверьте корректность использования переменных и функций в шаблоне |
| Неверный Chat ID | Ошибка при получении идентификатора | Используйте метод `getUpdates` для подтверждения ID чата |

## Дополнительная информация

**См. также:**

- [Provisioning алертов](./provisioning.md) — декларативная настройка ресурсов алертинга
- [Основные концепции Grafana Alerting](./concepts.md) — базовые принципы работы системы оповещений
- [Интеграция с системами эскалации](./escalation_integrations.md) — подключение внешних инструментов эскалации инцидентов
