# Интеграция Grafana с Telegram — Настройка уведомлений

## Определения

**Telegram-интеграция** — нативный контакт-пойнт Grafana для отправки уведомлений об оповещениях в чаты и каналы мессенджера Telegram.

**Текущая версия (февраль 2026):** Grafana 12.x (требуется версия 9.0 или выше для нативной поддержки; для версий ниже 9.0 используется механизм Webhook).

## Базовые концепции

### Преимущества Telegram как канала уведомлений

| Преимущество | Описание |
| :--- | :--- |
| **Мобильность** | Push-уведомления на мобильных устройствах инженеров. |
| **Форматирование** | Поддержка Markdown и HTML для выделения важной информации и вставки ссылок. |
| **Мультимедиа** | Возможность отправки скриншотов панелей (Snapshots) для мгновенного визуального контекста. |
| **Группировка** | Возможность создания отдельных чатов для разных команд, проектов или уровней критичности. |
| **Надежность** | Высокая доступность сервиса и простота настройки через Bot API. |

### Требования

| Компонент | Требование |
| :--- | :--- |
| **Grafana** | Версия 9.0 или выше (рекомендуется 12.x для работы с современными шаблонами). |
| **Telegram Bot** | Токен, полученный от @BotFather. |
| **Chat ID** | Идентификатор чата, группы или канала. |
| **Image Renderer** | Дополнительный сервис (Grafana Image Renderer) для возможности отправки скриншотов. |
| **Доступность API** | API `api.telegram.org` должен быть доступен со стороны сервера Grafana (напрямую или через прокси). |

### Получение реквизитов

**Шаг 1: Создание бота**
1. В Telegram найдите официальный аккаунт `@BotFather`.
2. Отправьте команду `/newbot`.
3. Укажите имя (display name) и уникальное имя пользователя (username) для бота.
4. Скопируйте полученный **токен** (формат: `1234567890:ABC...`).
   *   **Важно:** Никогда не храните токен в открытом виде в публичных репозиториях или файлах конфигурации без защиты.

**Шаг 2: Получение Chat ID**
1. Добавьте созданного бота в целевой чат или канал.
2. Для каналов: обязательно назначьте бота администратором с правом публикации сообщений.
3. Отправьте любое сообщение в этот чат.
4. Выполните запрос к API для получения идентификатора:
   ```bash
   curl "https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getUpdates"
   ```
5. Найдите в JSON-ответе объект `"chat":{"id":<CHAT_ID>}`.
   *   Для каналов ID обычно начинается с префикса `-100` (например, `-1001234567890`).

## Новые возможности (Grafana 12.x)

### Изображения в уведомлениях
Grafana позволяет прикреплять к сообщениям скриншоты панелей, на которых сработал алерт.
- **Настройка:** В параметрах контакт-пойнта включите опцию **"Include image"** (uploadImage: true).
- **Механизм:** Grafana задействует Image Renderer для создания снимка и передает его боту для отправки. Это критически важно для быстрой оценки ситуации без входа в веб-интерфейс.

### Тихие уведомления и режимы тишины
1. **Disable Sound:** Параметр `disable_notification: true` позволяет боту доставлять сообщения без звукового сигнала (полезно для уровня `info` или ночного времени).
2. **Mute Timings:** Настройка интервалов (Alerting > Notification policies > Mute Timings), когда уведомления в Telegram не должны отправляться (например, время еженедельного обслуживания БД).
3. **Silences:** Кратковременное подавление уведомлений для конкретного инстанса или сервиса во время проведения аварийных работ.

## Безопасность и секреты

Для защиты чувствительных данных (токенов) рекомендуется использовать переменные окружения. Grafana поддерживает интерполяцию `${VAR_NAME}` в YAML-файлах провиженинга.

```yaml
botToken: ${TELEGRAM_BOT_TOKEN}
```

## Практические сценарии

### Базовая конфигурация контакт-пойнта

Пример настройки через YAML (Provisioning) с использованием переменных окружения.

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

---

### Расширенный шаблон с форматированием (Critical)

Использование MarkdownV2 для детального отображения критических инцидентов.

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

Краткий шаблон для экономии места на экране мобильного устройства.

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

            *Текущее значение:* {{ $value }}
            *Время:* {{ .StartsAt.Format "15:04 02.01" }}

            [Открыть в Grafana]({{ .ExternalURL }})
            {{ end }}
```

---

### Политики уведомлений (Маршрутизация в Telegram)

Настройка логики распределения алертов по разным чатам.

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
- **`group_wait`**: Время ожидания дополнительных алертов перед отправкой первого сообщения (агрегация).
- **`group_interval`**: Задержка перед отправкой уведомления о появлении нового алерта в уже активной группе.
- **`repeat_interval`**: Время, через которое уведомление будет отправлено повторно, если алерт все еще активен.

---

### Диагностика и решение проблем

| Проблема | Вероятная причина | Решение |
| :--- | :--- | :--- |
| Уведомления не доставляются | Некорректный токен бота | Проверьте точность токена в @BotFather. Убедитесь, что переменная окружения загружена. |
| Бот не отправляет сообщения | Бот не добавлен в чат или канал | Добавьте бота в целевой чат или канал. |
| Бот не пишет в канал | Отсутствуют права администратора | Назначьте бота администратором канала с правом публикации сообщений. |
| Ошибка соединения с API | Ограничение доступа к `api.telegram.org` | Проверьте сетевые настройки, брандмауэр и параметры прокси в Grafana. |
| Сообщения приходят пустыми | Ошибка в синтаксисе шаблона Go | Проверьте корректность использования переменных и функций в шаблоне через Preview в UI. |
| Неверный Chat ID | Ошибка при получении идентификатора | Используйте метод `getUpdates` для подтверждения актуального ID чата. |
| Нет изображений | Проблема с Image Renderer | Проверьте статус сервиса рендеринга и сетевой доступ к нему со стороны Grafana. |

## Дополнительная информация

**См. также:**

- [Provisioning алертов](./provisioning.md) — декларативная настройка ресурсов алертинга.
- [Основные концепции Grafana Alerting](./concepts.md) — базовые принципы работы системы оповещений.
- [Интеграция с системами эскалации](./escalation_integrations.md) — подключение внешних инструментов эскалации инцидентов.
