# Интеграция Grafana с Telegram — Настройка уведомлений

## Определения

**Telegram-интеграция** — нативный контакт-пойнт Grafana для отправки уведомлений об оповещениях в чаты, группы и каналы мессенджера Telegram через официальное Bot API.

**Bot API** — HTTP-интерфейс Telegram для управления ботом (отправка сообщений, получение обновлений, управление вебхуками). Документация: https://core.telegram.org/bots/api

**BotFather** — официальный бот Telegram (`@BotFather`), через который создаются и регистрируются другие боты. Выдаёт уникальный токен доступа.

**Chat ID** — числовой идентификатор чата, группы или канала. Для супергрупп и каналов ID начинается с префикса `-100`. Используется как целевой адрес доставки.

**Contact point (Контакт-пойнт)** — декларативное описание канала доставки уведомления (Telegram, Slack, Email, Webhook) и шаблона сообщения. В Grafana контакт-пойнт Telegram использует нативный тип `telegram`.

**Notification policy (Политика уведомлений)** — правило маршрутизации экземпляров алертов по меткам к контакт-пойнтам, включая группировку (`group_by`) и тайминги (`group_wait`, `group_interval`, `repeat_interval`).

**MarkdownV2** — строгий поднабор Markdown, поддерживаемый Telegram для форматирования сообщений. Требует обязательного экранирования спецсимволов: `_`, `*`, `[`, `]`, `(`, `)`, `~`, `` ` ``, `>`, `#`, `+`, `-`, `=`, `|`, `{`, `}`, `.`, `!`.

**Image Renderer (Рендерер изображений)** — компонент Grafana, отвечающий за генерацию скриншотов панелей. В Grafana 11+ используется встроенный рендерер на базе headless Chromium; внешний `grafana-image-renderer` поддерживается как альтернатива.

**Mute Timing** — именованное расписание (Time Interval), привязанное к политике уведомлений, в рамках которого доставка уведомлений подавляется. Противоположность — `active_time_intervals` (алертит только внутри указанных окон).

**Актуальность (октябрь 2026):** Информация проверена для Grafana 13.3.x / 12.x (LTS). Текущая стабильная ветка — 13.3.x; 12.x — поддержка безопасности (LTS); 11.x — EOL (июнь 2026); 10.x — EOL (июнь 2025). Нативная поддержка Unified Alerting является стандартом; использование внешних адаптеров рекомендуется только для специфических задач фильтрации. Актуальная версия Telegram Bot API — 10.3 (август 2026).

## Базовые концепции

### Архитектура доставки уведомлений

Grafana Alerting доставляет уведомление в Telegram по следующему пути:

1. **Оценка правила (Evaluator):** Планировщик запускает конвейер выражений (Expressions) согласно интервалу группы. При истинности условия алерт переходит в `Pending`, затем (после `for`) в `Alerting`.
2. **Alertmanager:** Встроенный компонент Grafana принимает активные алерты, группирует их по меткам (`group_by`), применяет политики маршрутизации, Silences и Mute Timings.
3. **Контакт-пойнт Telegram:** Alertmanager вызывает Telegram Bot API (`sendMessage` или `sendPhoto`), передавая отформатированное сообщение.
4. **Telegram Bot API:** Telegram доставляет сообщение в целевой чат/группу/канал.

> **Важно:** Для доставки скриншотов панелей Alertmanager вызывает рендерер изображений до отправки сообщения. Если рендерер недоступен или отключён, сообщение отправляется без изображения (ошибка логируется, но не блокирует доставку текста).

### Преимущества Telegram как канала уведомлений

| Преимущество | Описание |
| :--- | :--- |
| **Мобильность** | Push-уведомления на мобильных устройствах инженеров. |
| **Форматирование** | Поддержка `MarkdownV2` и `HTML` для выделения важной информации и вставки ссылок. |
| **Мультимедиа** | Возможность отправки скриншотов панелей (Snapshots) для мгновенного визуального контекста. |
| **Группировка** | Возможность создания отдельных чатов для разных команд, проектов или уровней критичности. |
| **Надежность** | Высокая доступность сервиса и простота настройки через Bot API. |

### Типы целевых чатов

Telegram Bot API поддерживает три типа целей для доставки:

| Тип | Chat ID | Особенности настройки |
| :--- | :--- | :--- |
| **Личный чат (Private)** | Положительное число (например, `123456789`) | Бот должен быть запущен пользователем (`/start`). Подходит для индивидуальных дежурных. |
| **Группа (Group)** | Отрицательное число (например, `-1001234567890`) | Бот добавляется в группу как обычный участник. Достаточно прав на отправку сообщений. |
| **Канал (Channel)** | Отрицательное число с префиксом `-100` | Бот назначается администратором с правом публикации сообщений. Подходит для широковещательных уведомлений. |

> **Приватность групп:** в супергруппах по умолчанию включён режим `Chat privacy: off` для ботов (в настройках группы). Если бот не видит сообщения, отключите隐私 режим через `@BotFather` → `/setprivacy` → `Disable` или через настройки группы.

### Ограничения Telegram Bot API (Bot API 10.3, 2026)

| Ограничение | Значение | Последствие при превышении |
| :--- | :--- | :--- |
| **Длина сообщения** | 4096 UTF-8 символов (`sendMessage`) | `400 Bad Request: message is too long`; при `parse_mode` ≠ `None` обрезка может сломать разметку. |
| **Одиночный чат** | 1 сообщение/сек на чат | `429 Too Many Requests: retry after N` (N — целое число секунд). |
| **Группа/канал** | 20 сообщений/мин на группу | `429`; лимит считается отдельно от общего бота. |
| **Рассылка (bulk)** | ~30 сообщений/сек на бота | `429`; при оплате через Stars — до 1000/сек. |
| **Размер изображения** | 10 МБ для `sendPhoto` (JPEG/PNG) | `400 Bad Request: PHOTO_INVALID_DIMENSIONS` или аналог. |
| **Спецсимволы MarkdownV2** | Жёсткое требование экранирования | `400 Bad Request: can't parse entities`. |

> **Важно:** лимиты считаются **на токен бота** и **на чат** одновременно. Смена IP/прокси не сбрасывает счётчик — как один токен, так и один общий budget. При параллельных инстансах Grafana (HA, multiple replicas) используйте общий бот с `group_by`, избегайте дублирования одних и тех же алертов в один чат.

### Локальный Bot API Server (без доступа к telegram.org)

Если `api.telegram.org` недоступен (корпоративный брандмауэр, изоляция сетей), можно развернуть [официальный локальный Bot API Server](https://core.telegram.org/bots/api#using-a-local-bot-api-server) (`telegram-bot-api`). Преимущества:

- Отправка файлов до 2000 МБ (вместо 20 МБ у публичного API).
- Отправка по локальному пути (file URI).
- Собственный вебхук-URL и произвольный порт.
- Отсутствие лимитов на количество ботов/чатов (только ресурсы хоста).

Для этого в Grafana в контакт-пойнте Telegram укажите `apiURL` (опциональное поле, по умолчанию `https://api.telegram.org`) — адрес вашего локального сервера.

### Требования

| Компонент | Требование |
| :--- | :--- |
| **Grafana** | Версия 12.x (LTS) или 13.3.x (текущая); 11.x — EOL (июнь 2026). |
| **Telegram Bot** | Токен, полученный от @BotFather. |
| **Chat ID** | Идентификатор чата, группы или канала. |
| **Image Renderer** | Встроенный рендерер (на базе Chromium) или внешний сервис Grafana Image Renderer. |
| **Доступность API** | API `api.telegram.org` должен быть доступен (напрямую или через прокси). |
| **Chromium** | Установленный Chromium в системе или доступный в Docker-образе (для скриншотов). |

### Получение реквизитов

**Шаг 1: Создание бота**
1. В Telegram найдите официальный аккаунт `@BotFather`.
2. Отправьте команду `/newbot`.
3. Укажите имя (display name) и уникальное имя пользователя (username, например, `myorg-grafana-bot`).
4. Скопируйте полученный **токен** (формат: `1234567890:ABC...`).
   *   **Важно:** Никогда не храните токен в открытом виде. Используйте секреты (переменные окружения, Vault, Kubernetes Secrets).

**Шаг 2: Настройка бота для групп/каналов**
1. Добавьте созданного бота в целевой чат или канал.
2. Для каналов: назначьте бота администратором с правом публикации сообщений.
3. Для групп: отключите режим privacy бота через `@BotFather` → `/setprivacy` → `Disable` (иначе бот не увидит сообщения участников).
4. Отправьте любое сообщение в этот чат от лица участника (не от бота).

**Шаг 3: Получение Chat ID**
1. Выполните запрос к API для получения идентификатора:
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
2. Найдите в ответе объект `"chat":{"id":<CHAT_ID>}`. Для каналов и супергрупп ID начинается с `-100`.
3. **Альтернативный способ:** используйте бота `@username_to_id_bot` или `@getidsbot` для получения ID без вызова API напрямую.

## Предварительные требования

*   **Версия:** Grafana 12.x (LTS) или 13.3.x (текущая); 11.x — EOL (июнь 2026). Стандарт — Unified Alerting (включён по умолчанию с 9.x).
*   **Права:** пользователь Grafana с ролью `Admin` или `Alerting > Edit rules`.
*   **Источник данных:** настроен и доступен (Prometheus/Mimir/Loki/SQL).
*   **Сеть:** выходной доступ `api.telegram.org:443` из узла Grafana (напрямую или через прокси).
*   **Chromium:** для скриншотов — установленный Chromium или включённый встроенный рендерер.
*   **Секреты:** переменные окружения для токенов заданы в окружении процесса Grafana.

## Практические сценарии

### 1. Базовая конфигурация через UI

Этот сценарий описывает настройку через веб-интерфейс Grafana (без файлового провиженинга).

**Шаг 1:** Откройте **Alerting → Contact points → + Add contact point**.

**Шаг 2:** Заполните поля:
*   **Name:** `team-devops-telegram`
*   **Integration:** выберите `Telegram`
*   **Bot Token:** `${TELEGRAM_BOT_TOKEN}` (если включена интерполяция) или прямой токен
*   **Chat ID:** `-1001234567890`
*   **Parse mode:** `MarkdownV2` (рекомендуется) или `HTML`
*   **Disable notification:** включите, если не нужен звук (для уровня `info`)
*   **Upload image:** включите для прикрепления скриншотов
*   **Message:** вставьте шаблон (см. пример ниже)

**Шаг 3:** Нажмите **Test**. Должно прийти тестовое сообщение в целевой чат. Если сообщение не пришло — проверьте раздел диагностики.

**Шаг 4:** Назначьте контакт-пойнт в политике уведомлений: **Alerting → Notification policies** → выберите политику → измените контакт-пойнт.

```yaml
# Пример шаблона для UI (вставка в поле Message)
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

### 2. Декларативная конфигурация (Provisioning)

Для IaC-подхода используйте файловый провиженинг. Структура директорий:

```
/etc/grafana/provisioning/alerting/
├── contactpoints/
│   └── telegram.yaml
├── policies/
│   └── telegram-routing.yaml
└── templates/
    └── telegram-templates.yaml
```

**Важно:** См. [Provisioning алертов](./provisioning.md) для полной схемы провиженинга, горячей перезагрузки и UID-ограничений.

#### 2.1 Базовый контакт-пойнт

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

#### 2.2 Расширенный шаблон (Critical) с MarkdownV2

Telegram строго требует экранирования спецсимволов (`_`, `*`, `.`, `!`, `-` и др.) в MarkdownV2. Используйте фильтр `reReplaceAll` в Go-шаблоне:

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

> **Почему экранирование важно:** Telegram отклоняет сообщение с неэкранированным символом, возвращая `400 Bad Request: can't parse entities`. Чаще всего страдают `_` (курсив), `*` (жирный), `[` (ссылка) и `.` (в версиях/инстансах). Экранируйте все динамические значения.

#### 2.3 Шаблон для информационных оповещений (Info)

Краткий шаблон для экономии места в рабочих чатах:

```yaml
contactPoints:
  - orgId: 1
    name: telegram-info
    receivers:
      - uid: telegram-info-receiver
        type: telegram
        settings:
          botToken: ${TELEGRAM_BOT_TOKEN}
          chatId: "-1001234567890"
          disableNotification: true
          message: |
            {{ define "telegram.info.message" }}
            ℹ️ *Информация*

            {{ .CommonAnnotations.summary }}
            {{ if .CommonAnnotations.description }}
            {{ .CommonAnnotations.description }}
            {{ end }}
            [Открыть в Grafana]({{ .ExternalURL }})
            {{ end }}
```

#### Многоканальная доставка и деревья политик (Grafana 13.2+, GA)

Один контакт-пойнт может отправлять в несколько чатов через список получателей. Однако в текущих версиях Grafana (12.x/13.x) поле `chatId` в settings поддерживает одно значение. Для отправки в несколько чатов создайте отдельные ресиверы или используйте политику уведомлений с маршрутизацией:

**Вариант A — несколько ресиверов в одном контакт-пойнте:**

```yaml
# provisioning/alerting/contactpoints/telegram-multi.yaml
apiVersion: 1
contactPoints:
  - orgId: 1
    name: telegram-ops-critical
    receivers:
      - uid: telegram-ops-critical-1
        type: telegram
        settings:
          botToken: ${TELEGRAM_BOT_TOKEN}
          chatId: "-1001234567890"   # Основной чат ops
          parse_mode: "MarkdownV2"
          uploadImage: true
          message: |
            {{ define "telegram.critical.message" }}
            ...
            {{ end }}
      - uid: telegram-managers-critical-1
        type: telegram
        settings:
          botToken: ${TELEGRAM_BOT_TOKEN}
          chatId: "-1009876543210"   # Чат руководителей
          parse_mode: "MarkdownV2"
          disableNotification: false
          message: |
            {{ define "telegram.critical.manager" }}
            ...
            {{ end }}
```

**Вариант B — независимые деревья политик (Grafana 13.2+, GA).** Флаг `alertingMultiplePolicies` включён по умолчанию с 13.2. Позволяет создавать именованные деревья политик, привязывать к ним алерты и управлять доступом по ролям. Существующие конфигурации продолжают работать через дефолтную политику; миграция пошаговая. Подробнее в [Provisioning](./provisioning.md) и [best practices](./best_practices.md).

### 3. Политики уведомлений и маршрутизация

Политики определяют, куда отправится алерт, основываясь на его метках. Дерево строится от общего к частному.

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
        group_interval: 30m
        repeat_interval: 24h
        active_time_intervals:
          - business-hours
```

**Ключевые параметры:**
*   `group_by` — метки для агрегации алертов в одно сообщение. Избегайте высокой кардинальности (`pod`, `instance`).
*   `group_wait` — задержка перед первой отправкой для сбора группы алертов.
*   `group_interval` — пауза между повторными отправками для новых алертов в группе.
*   `repeat_interval` — период повтора уведомления об уже сработавшем алерте.
*   `continue: true` — опция на дочерней политике, позволяющая алерту также матчиться с «братьями» родителя (по умолчанию выключена).
*   `active_time_intervals` — подавляет уведомления вне указанных окон (см. `business-hours` в примере ниже).

**Пример Mute Timing + Active Time Interval:**

```yaml
# provisioning/alerting/mute_timings/schedules.yaml
apiVersion: 1
muteTimes:
  - orgId: 1
    name: "Maintenance-Windows"
    time_intervals:
    - times:
      - start_time: "02:00"
        end_time: "04:00"
      weekdays: ["saturday", "sunday"]
      location: "Europe/Moscow"
  - orgId: 1
    name: "Business-Hours"
    time_intervals:
    - times:
      - start_time: "09:00"
        end_time: "19:00"
      weekdays: ["monday:friday"]
      location: "Europe/Moscow"
```

## Новые возможности (2026 Update)

### Изображения в уведомлениях

Grafana позволяет прикреплять к сообщениям скриншоты панелей.
*   **Настройка:** В параметрах контакт-пойнта включите опцию **"Include image"** (`uploadImage: true`).
*   **Механизм (Grafana 11+):** Предпочтительно использование встроенного рендерера (`headless_chrome`).
*   **Конфигурация (grafana.ini):**
  ```ini
  [screenshots]
  enabled = true
  method = headless_chrome
  ```
*   **Проверка:** убедитесь, что Chromium доступен в PATH или укажите полный путь в `[screenshots]` → `chromium` (или `chrome`).

### Тихие уведомления и режимы тишины

1. **Disable Sound:** Параметр `disable_notification: true` позволяет боту доставлять сообщения без звукового сигнала (полезно для уровня `info`).
2. **Mute Timings:** Настройка интервалов (Alerting > Notification policies > Mute Timings), когда уведомления не должны отправляться.
3. **Silences:** Кратковременное подавление уведомлений для конкретного инстанса во время работ.
4. **Resolved Messages:** Возможность включить/выключить уведомления о восстановлении (`disableResolveMessage: false` в контакт-пойнте).
5. **Protect Content:** Telegram-параметр `protect_content` (в settings контакт-пойнта) предотвращает пересылку и сохранение сообщения. Используется для конфиденциальных алертов.
6. **Несколько деревьев политик:** с Grafana 13.2 (GA) флаг `alertingMultiplePolicies` позволяет разделять маршрутизацию на независимые именованные деревья (подробнее в разделе «Многоканальная доставка» выше).

## Безопасность и секреты

Для защиты токенов используйте переменные окружения. В `grafana.ini` должна быть включена интерполяция:

```ini
[security]
enable_env_vars_interpolation = true
```

Пример в YAML:
```yaml
botToken: ${TELEGRAM_BOT_TOKEN}
```

**Паттерны управления секретами:**
*   **Docker / systemd:** передача через `environment:` или `Environment=`.
*   **Kubernetes:** использование `Secret` и монтирование как переменных окружения (`env.valueFrom.secretKeyRef`).
*   **HashiCorp Vault:** внешний секрет-менеджер с агентом или через плагин.
*   **Grafana Cloud:** переменные окружения в окружении сервиса или Terraform-провайдер.

> **Важно:** интерполяция НЕ применяется к полям `annotations` правил, `relativeTimeRange`, `data.model`, `name`/`time_intervals` mute timings и `name`/`template` групп шаблонов. Секреты в этих полях не подставятся.

**Права бота:**
*   Для личных чатов: бот должен быть запущен пользователем (`/start`).
*   Для групп: бот как участник; рекомендуется отключить privacy через `@BotFather` → `/setprivacy` → `Disable`.
*   Для каналов: бот как администратор с правом публикации сообщений.

## Проверка корректности (Validation)

*   **Тест контакт-пойнта:** на странице Contact point нажмите **Test** — должно прийти тестовое сообщение с ожидаемым шаблоном. Это проверяет корректность `settings`, токена и Chat ID.
*   **Предпросмотр шаблона:** в редакторе контакт-пойнта используйте **Preview** для проверки развёртки Go-шаблона с реальными данными алерта.
*   **Список правил:** `Alerting → Alert rules` — состояние (`Normal`/`Pending`/`Alerting`) и время последней оценки.
*   **State history:** `Alerting → History` видны все переходы состояний, включая подавленные тишиной/mute (в OSS/Enterprise требует настроенного Loki и тоггла `alertingCentralAlertHistory`).
*   **Доставка:** во время `Alerting` проверьте канал (Telegram) и `Alerting → Silences/Notifications` (в Cloud/Enterprise — лог доставки).
*   **Логи Grafana:** при ошибках проверьте `logger=alerting` и `logger=rendering` (для скриншотов).

## Диагностика и решение проблем

| Проблема | Вероятная причина | Решение |
| :--- | :--- | :--- |
| Ошибка `401 Unauthorized` | Некорректный токен бота | Проверьте токен через `getMe` API: `curl https://api.telegram.org/bot<TOKEN>/getMe` |
| Ошибка `400 Bad Request: can't parse entities` | Ошибка в MarkdownV2 | Проверьте экранирование спецсимволов (`_`, `*`, `[`, `]`, `.`). Используйте `reReplaceAll` в шаблоне. |
| Ошибка `400 Bad Request: message is too long` | Сообщение превышает 4096 символов | Сократите шаблон или разбейте алерт на несколько частей (используйте `{{ range .Alerts }}`). |
| Ошибка `429 Too Many Requests` | Превышен лимит частоты Bot API | Добавьте задержку (`retry after X`), увеличьте `group_interval`/`repeat_interval`. |
| Бот не отправляет сообщения | Бот не добавлен в чат / нет прав | Добавьте бота, для каналов назначьте администратором. |
| Бот не видит сообщения в группе | Privacy mode включён | Отключите через `@BotFather` → `/setprivacy` → `Disable`. |
| Ошибка соединения / таймаут | Ограничение доступа к API | Проверьте сетевые настройки, прокси, DNS. |
| Сообщения приходят пустыми | Ошибка в шаблоне Go | Проверьте переменные через Preview в UI. Убедитесь, что аннотации (`summary`, `description`) присутствуют у алерта. |
| Нет изображений | Проблема с рендерером | Проверьте логи Grafana (`logger=rendering`), наличие Chromium, `[screenshots] enabled = true`. |
| Уведомление о восстановлении не приходит | `sendResolved` отключён | Включите `disableResolveMessage: false` в контакт-пойнте. |

## Лучшие практики и очистка (Best Practices & Cleanup)

*   **Группируйте по стабильным меткам:** `group_by: ['alertname', 'service']`, избегайте `pod`/`instance` — это снижает шум и нагрузку.
*   **Используйте `for` и `keep_firing_for`:** предотвращают дребезг и каскад `resolve → fire`.
*   **Тестируйте контакт-пойнты:** всегда нажимайте **Test** перед продакшеном. Проверяйте на реальном чате, а не только в логах.
*   **Создавайте отдельные чаты по критичности:** critical → PagerDuty/Telegram звук, warning → Telegram без звука, info → Telegram с `disable_notification`.
*   **Экранируйте MarkdownV2:** всегда экранируйте динамические значения. Используйте единый helper-шаблон для экранирования.
*   **Секреты в окружении:** не коммитьте токены. Используйте `${ENV_VAR}` с `enable_env_vars_interpolation = true`.
*   **Мониторьте доставку:** добавьте мета-алерт на `rate(alertmanager_notifications_failed_total[5m]) > 0`.
*   **Очистка:** удаляйте временные Silences после инцидентов; регулярно пересматривайте Mute Timings; удаляйте неиспользуемые контакт-пойнты и политики из файлов провиженинга.
*   **Версионирование:** храните конфигурацию в Git, делайте code review для изменений в шаблонах и маршрутизации.

## Граничные случаи (Edge Cases)

*   **Длина сообщения:** Telegram ограничивает `sendMessage` 4096 символами. При превышении — ошибка. Используйте `range .Alerts` для списка или сокращайте шаблон.
*   **Многомерные алерты:** один алерт на 100+ экземпляров может создать слишком длинное сообщение. Ограничьте `range` или используйте `group_by`.
*   **Пустые аннотации:** если `summary` или `description` отсутствуют у алерта, шаблон должен корректно обрабатывать пустые значения (конструкции `{{ if ... }}`).
*   **Временные зоны:** Mute Timings и Time Intervals учитывают `location`; несовпадение с локальным временем команды — частый источник «почему ночью пришло уведомление».
*   **Наследование в дереве политик:** дочерняя политика наследует контакт-пойнт и тайминги родителя — неочевидное поведение при каскадных политиках.
*   **Несколько Alertmanager:** каждый Alertmanager хранит **собственные** независимые ресурсы (contact points, policies, silences) — они не шерятся между собой.
*   **Inhibition (Grafana 13.2+, GA):** привязан к Alertmanager и подавляет только алерты, управляемые им; неверная настройка молча глушит алерты; API доступен без бета-статуса, выделенного UI нет — настройка через `AlertmanagerConfig` (CRD Prometheus Operator) или App Platform API.
*   **Proxy и корпоративные сети:** при блокировке `api.telegram.org` настройте прокси в `grafana.ini` или на уровне сети (NAT, firewall rules).

## Дополнительная информация

**См. также:**

*   [Provisioning алертов](./provisioning.md) — декларативная настройка, IaC, горячая перезагрузка.
*   [Основные концепции Alerting](./concepts.md) — архитектура Unified Alerting, конвейер выражений, состояния.
*   [Лучшие практики алертинга](./best_practices.md) — рекомендации по настройке `for`, группировке, борьбе с шумом.
*   [Интеграция с системами эскалации](./escalation_integrations.md) — внешние инструменты управления инцидентами (PagerDuty, Opsgenie).
