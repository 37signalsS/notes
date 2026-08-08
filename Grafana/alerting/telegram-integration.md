# Интеграция Grafana с Telegram — Настройка уведомлений

## Определения

**Telegram-интеграция** — нативный контакт-пойнт Grafana для отправки уведомлений об оповещениях в чаты, группы и каналы мессенджера Telegram через официальное Bot API.

**Актуальность (август 2026):** Информация проверена для Grafana 12.x и 13.x. Нативная поддержка Unified Alerting является стандартом; использование внешних адаптеров рекомендуется только для специфических задач фильтрации.

## Базовые концепции

### Преимущества Telegram как канала уведомлений

| Преимущество | Описание |
| :--- | :--- |
| **Мобильность** | Push-уведомления на мобильных устройствах инженеров. |
| **Форматирование** | Поддержка `MarkdownV2` и `HTML` для выделения важной информации и вставки ссылок. |
| **Мультимедиа** | Возможность отправки скриншотов панелей (Snapshots) для мгновенного визуального контекста. |
| **Группировка** | Возможность создания отдельных чатов для разных команд, проектов или уровней критичности. |
| **Надежность** | Высокая доступность сервиса и простота настройки через Bot API. |

### Требования

| Компонент | Требование |
| :--- | :--- |
| **Grafana** | Версия 10.0+ (рекомендуется 13.x для работы с современными шаблонами). |
| **Telegram Bot** | Токен, полученный от @BotFather. |
| **Chat ID** | Идентификатор чата, группы или канала. |
| **Image Renderer** | Встроенный рендерер (на базе Chromium) или внешний сервис Grafana Image Renderer. |
| **Доступность API** | API `api.telegram.org` должен быть доступен (напрямую или через прокси). |

### Получение реквизитов

**Шаг 1: Создание бота**
1. В Telegram найдите официальный аккаунт `@BotFather`.
2. Отправьте команду `/newbot`.
3. Укажите имя (display name) и уникальное имя пользователя (username).
4. Скопируйте полученный **токен** (формат: `1234567890:ABC...`).
   *   **Важно:** Никогда не храните токен в открытом виде. Используйте секреты.

**Шаг 2: Получение Chat ID**
1. Добавьте созданного бота в целевой чат или канал.
2. Для каналов: назначьте бота администратором с правом публикации сообщений.
3. Отправьте любое сообщение в этот чат.
4. Выполните запрос к API для получения идентификатора:
   ```bash
   curl -s "https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getUpdates" | jq
   ```
   **Ожидаемый результат (фрагмент):**
   ```json
   {
     "ok": true,
     "result": [
       {
         "message": {
           "chat": {
             "id": -1001234567890,
             "title": "SRE Alerts Group",
             "type": "supergroup"
           },
           "text": "/start"
         }
       }
     ]
   }
   ```
5. Найдите в ответе объект `"chat":{"id":<CHAT_ID>}`. Для каналов ID начинается с `-100`.

## Новые возможности (2026 Update)

### Изображения в уведомлениях
Grafana позволяет прикреплять к сообщениям скриншоты панелей.
- **Настройка:** В параметрах контакт-пойнта включите опцию **"Include image"** (uploadImage: true).
- **Механизм (Grafana 11+):** Предпочтительно использование встроенного рендерера (`headless_chrome`).
- **Конфигурация (grafana.ini):**
  ```ini
  [screenshots]
  enabled = true
  method = headless_chrome
  ```

### Тихие уведомления и режимы тишины
1. **Disable Sound:** Параметр `disable_notification: true` позволяет боту доставлять сообщения без звукового сигнала (полезно для уровня `info`).
2. **Mute Timings:** Настройка интервалов (Alerting > Notification policies > Mute Timings), когда уведомления не должны отправляться.
3. **Silences:** Кратковременное подавление уведомлений для конкретного инстанса во время работ.
4. **Resolved Messages:** Возможность включить/выключить уведомления о восстановлении (Send resolved).

## Безопасность и секреты

Для защиты токенов используйте переменные окружения. В `grafana.ini` должна быть включена интерполяция:
```ini
[utils]
enable_env_vars_interpolation = true
```

Пример в YAML:
```yaml
botToken: ${TELEGRAM_BOT_TOKEN}
```

## Практические сценарии

### 1. Базовая конфигурация контакт-пойнта

```yaml
# provisioning/alerting/contactpoints/telegram.yaml
apiVersion: 1
contactPoints:
  - orgId: 1
    name: team-devops-telegram
    receivers:
      - uid: telegram-receiver-base
        type: telegram
        settings:
          botToken: ${TELEGRAM_BOT_TOKEN}
          chatId: "-1001234567890"
          uploadImage: true
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

### 2. Расширенный шаблон (Critical) с MarkdownV2

Telegram строго требует экранирования спецсимволов (`_`, `*`, `.`, `!`, `-` и др.) в MarkdownV2.

```yaml
contactPoints:
  - orgId: 1
    name: telegram-critical
    receivers:
      - uid: telegram-critical-receiver
        type: telegram
        settings:
          botToken: ${TELEGRAM_BOT_TOKEN}
          chatId: "${TELEGRAM_CRITICAL_CHAT_ID}"
          parse_mode: "MarkdownV2"
          message: |
            {{ define "telegram.critical.message" }}
            *КРИТИЧЕСКОЕ ОПОВЕЩЕНИЕ*

            *Суть:* {{ .CommonAnnotations.summary | reReplaceAll "-" "\\-" }}

            {{ if .CommonAnnotations.description }}
            _{{ .CommonAnnotations.description | reReplaceAll "_" "\\_" }}_
            {{ end }}

            ------------------------------
            *Информация:*
            - Название: `{{ .CommonLabels.alertname | reReplaceAll "_" "\\_" }}`
            - Сервис: `{{ .CommonLabels.service | reReplaceAll "_" "\\_" }}`
            - Инстанс: `{{ .CommonLabels.instance | reReplaceAll "." "\\." }}`

            *Время:*
            - Начало: {{ .StartsAt.Format "02.01.2006 15:04 MSK" }}

            [Открыть в Grafana]({{ .ExternalURL }})
            {{ end }}
```

### 3. Шаблон для предупреждающих оповещений (Warning)

Краткий шаблон для экономии места.

```yaml
contactPoints:
  - orgId: 1
    name: telegram-warning
    receivers:
      - uid: telegram-warning-receiver
        type: telegram
        settings:
          botToken: ${TELEGRAM_BOT_TOKEN}
          chatId: "-1001234567890"
          message: |
            {{ define "telegram.warning.message" }}
            *ПРЕДУПРЕЖДЕНИЕ*

            {{ .CommonAnnotations.summary }}
            *Текущее значение:* {{ index .Values "B" }}
            *Время:* {{ .StartsAt.Format "15:04 02.01" }}

            [Открыть в Grafana]({{ .ExternalURL }})
            {{ end }}
```

## Политики уведомлений (Маршрутизация)

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
      - receiver: telegram-critical
        object_matchers:
          - ['severity', '=', 'critical']
        group_wait: 10s
        group_interval: 1m
        repeat_interval: 1h
      - receiver: telegram-warning
        object_matchers:
          - ['severity', '=', 'warning']
        group_wait: 1m
        group_interval: 10m
        repeat_interval: 4h
      - receiver: telegram-info
        object_matchers:
          - ['severity', '=', 'info']
        group_wait: 5m
        repeat_interval: 24h
        active_time_intervals:
          - business-hours
```

## Диагностика и решение проблем

| Проблема | Вероятная причина | Решение |
| :--- | :--- | :--- |
| Ошибка `401 Unauthorized` | Некорректный токен бота | Проверьте токен через `getMe` API. |
| Ошибка `400 Bad Request` | Ошибка в MarkdownV2 | Проверьте экранирование спецсимволов. |
| Бот не отправляет сообщения | Бот не добавлен в чат | Добавьте бота и дайте права администратора. |
| Ошибка соединения | Ограничение доступа к API | Проверьте сетевые настройки и прокси. |
| Сообщения приходят пустыми | Ошибка в шаблоне Go | Проверьте переменные через Preview в UI. |
| Нет изображений | Проблема с рендерером | Проверьте логи Grafana (`logger=rendering`) и наличие Chromium. |

## Дополнительная информация

**См. также:**

- [Provisioning алертов](./provisioning.md) — декларативная настройка.
- [Основные концепции Alerting](./concepts.md) — архитектура Unified Alerting.
- [Интеграция с системами эскалации](./escalation_integrations.md) — внешние инструменты управления инцидентами.
