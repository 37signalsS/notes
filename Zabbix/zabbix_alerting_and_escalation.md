# Zabbix — алертинг и эскалация

**Актуально для:** Zabbix 7.0 LTS / 7.4

Документ описывает механику оповещений: действия (Actions), операции, эскалацию, recovery/update-операции, каналы доставки (media types) и webhook. Принципы проектирования стратегии оповещений — в **[Лучших практиках](./zabbix_best_practices.md)**.

---

## Определения

* **Action (Действие)** — правило, определяющее, что делать при наступлении события: какие условия проверять, каким пользователям/группам и через какие каналы отправлять сообщения, какие команды выполнять.
* **Operation (Операция)** — конкретная задача внутри действия: `Send message`, `Remote command`, `Notify all involved`.
* **Escalation (Эскалация)** — последовательность шагов операции с течением времени, позволяющая повторять и поднимать оповещения до более высокого уровня.
* **Media type (Канал доставки)** — способ отправки уведомления: Email, SMS, custom script, Webhook.
* **User media** — персональные данные доставки в профиле пользователя (e-mail, телефон, ID в мессенджере) — обязательны для получения уведомлений.
* **Recovery operation** — операция, выполняемая при восстановлении проблемы.
* **Update operation** — операция, выполняемая при обновлении события (например, при подтверждении).
* **Webhook** — media type со встроенным JavaScript-кодом, выполняющим HTTP-вызовы для интеграции с внешними системами.

---

## Основные концепции

### Цепочка оповещений

Уведомление доходит только при выполнении всей цепочки:

1. **Событие** (Problem/OK от триггера либо discovery/autoregistration/internal).
2. **Action** с подходящими условиями (Conditions) и включённый.
3. **Operation**, которая отправляет сообщение в рамках шага эскалации.
4. **Media type**, работающий и включённый.
5. **User media** получателя, определённые в его профиле.

Отсутствие любого звена означает, что оповещение не придёт.

### Типы действий

| Тип действия | Источник событий |
|---|---|
| Trigger actions | Problem/OK от триггеров |
| Discovery actions | События network discovery |
| Autoregistration actions | События авторегистрации агентов |
| Internal actions | Внутренние события сервера (нет данных, неподдерживаемый элемент) |
| Service actions | События сервисных IT-услуг (SLA) |

### Условия (Conditions)

Действие выполняется только при совпадении событий с условиями: важность триггера, хост, хост-группа, тег (имя/значение), время события, проблема подтверждена/не подтверждена и т. д. Условия объединяются логикой AND. Для trigger actions доступны условия по подтверждению: `Event is not acknowledged`, `Event is acknowledged`.

### Операции

* **Send message** — отправка сообщения пользователям/группам через media type. `Send to media type` (переименовано из `Send only to` с 7.0.7) позволяет ограничить конкретным каналом. Сообщение может быть custom (своё) — для internal-событий через webhook custom message обязателен.
* **Remote command** — выполнение команды на хосте/группе/текущем хосте. Команда доступна, если ранее определена в global scripts с областью `Action operation`. На сервере команда выполняется столько раз, сколько выбрано целей.
* **Notify all involved** — повторная отправка всем, кто получил исходное уведомление о проблеме.

### Эскалация

* Шаги задаются диапазоном (например, от 1 до 5); шаг 1 — немедленные действия.
* **Минимальная длительность шага — 60 секунд.** При пересечении диапазонов шагов разных операций действует **меньшая** пользовательская длительность.
* В одном шаге может быть несколько операций.
* **Эскалация поддерживается только для problem-операций**, не для recovery.
* Макрос `{ESC.HISTORY}` содержит историю всех выполненных шагов эскалации (отправленные сообщения и команды).
* Если проблема разрешена, а настроено recovery-сообщение, оно уйдёт тем, кто получил хотя бы одно problem-сообщение в этом сценарии.

### Recovery- и Update-операции

* **Recovery operations:** поддерживают `Send message`, `Remote command`, `Notify all involved`. **Эскалация не поддерживается** — все операции выполняются на одном шаге одновременно.
* **Update operations:** выполняются при обновлении проблемы (например, подтверждении). Используются, чтобы уведомить ответственного о смене статуса.

### Пауза операций и отмена эскалации

* **Pause operations for symptom problems** — приостанавливает problem-эскалацию для проблем-симптомов (только trigger actions).
* **Pause operations for suppressed problems** — откладывает старт операций на период maintenance; после обслуживания выполняются все накопившиеся операции. Если снять галочку — операции выполняются и во время maintenance.
* **Notify about canceled escalations** — уведомление об отмене эскалации (при отключении хоста, элемента, триггера или действия). Сообщение содержит причину отмены и рассылается всем, кто ранее получил уведомления.

### Каналы доставки (Media types)

* **Email** — через SMTP.
* **SMS** — через внешний шлюз.
* **Custom script** — вызов скрипта.
* **Webhook** — JavaScript-код, выполняющий HTTP-запросы (HTTP GET/POST/PUT/DELETE, а также CONNECT/PATCH/HEAD/OPTIONS/TRACE).

Требования:

* Message templates (шаблоны сообщений) **обязательны** для всех методов, включая webhook и скрипты, не использующие дефолтные сообщения.
* User media **обязательны** в профиле получателя, независимо от метода.
* Для webhook параметры поддерживают пользовательские макросы и макросы `{ALERT.SENDTO}`, `{ALERT.SUBJECT}`, `{ALERT.MESSAGE}`.
* Webhook возвращает OK (опционально со списком тегов) или строку ошибки; при включённом `Process tags` возвращённые теги добавляются к проблеме (webhook должен возвращать хотя бы `{"tags":{}}`).
* `Include event menu entry` добавляет в меню события ссылку на внешний тикет.
* Тестирование media type ждёт ответа сервера до **65 секунд** (настраивается в Administration → General → Timeouts).

---

## Практические сценарии

### Предварительные требования

* Настроенный SMTP/SMS/внешний сервис.
* Права администратора.
* Для remote command — определённые global scripts.

### Сценарий 1. Email-уведомления

1. Alerts → Media types → Email: задать `SMTP server`, `SMTP helo`, `SMTP email`, порт, аутентификацию.
2. Проверить: кнопка **Test** — ввести получателя и убедиться, что письмо ушло.
3. В профиле пользователя (User settings → Media) добавить email-адрес и отметить нужные типы событий.
4. В шаблонах сообщений Email проверить наличие шаблона для problem.

### Сценарий 2. Действие с условиями

Alerts → Actions → Trigger actions → Create action:

* `Name`: `Notify Ops on High`.
* Conditions: `Trigger severity` ≥ `High`; `Host group` = `Production`; `Tag service` = `payment`.
* Operations (шаг 1): `Send message` → user group `Operations` → media type Email → custom message с макросом `{EVENT.NAME}`.
* Recovery operations: `Notify all involved`.

### Сценарий 3. Эскалация на 3 уровня

* Default operation step duration = `30m`.
* Steps: `1`–`5`.
* Шаг 1: Send message → `DB Admins`.
* Шаги 2–3: Send message → `DB Admins`.
* Шаг 4: Send message → `DB Manager`.
* Шаг 5: Remote command → перезапуск сервиса (если проблема не подтверждена).

Макрос `{ESC.HISTORY}` в сообщении покажет всю историю эскалации.

### Сценарий 4. Webhook (Slack/Telegram/Jira)

1. Скачать нужный `.yaml` из каталога `templates/media` и импортировать в Zabbix.
2. Настроить параметры webhook (URL, токен, канал) по инструкции Readme.md.
3. Добавить пользователя-бота в действие (`Send to users`).
4. При необходимости включить `Process tags` (сохранение ID тикета) и `Include event menu entry`.
5. Проверить кнопкой Test.

### Валидация

* Alerts → Actions: после события Monitoring → Problems у получателя должно появиться уведомление; проверить Reports → Action log.
* Тест media type в Alerts → Media types.
* Для remote command — проверить Reports → Action log (результат выполнения).

---

## Операции и команды

```bash
# Список действий через API
curl -s -X POST -H 'Content-Type: application/json-rpc' \
  -H 'Authorization: Bearer <TOKEN>' \
  -d '{"jsonrpc":"2.0","method":"action.get","params":{"output":"extend"},"id":1}' \
  http://zabbix.example.com/zabbix/api_jsonrpc.php
# → список действий с полями eventsource/status/name

# Список media types
# method: mediatype.get, params: {"output":"extend"}
```

| Сущность API | Назначение |
|---|---|
| `action.get` / `action.create` | Действия (condition/operation) |
| `mediatype.get` / `mediatype.create` | Каналы доставки |
| `usermedia.get` | Персональные каналы пользователя |
| `script.get` | Global scripts для remote command |

---

## Устранение неисправностей

| Симптом | Причина | Решение |
|---|---|---|
| Оповещения не приходят | Нет user media у получателя | Заполнить Media в профиле пользователя |
| Оповещения не приходят | Не определён message template для media type | Добавить шаблон сообщения (обязателен) |
| Оповещения не приходят | Действие выключено или не подходит по условиям | Проверить статус и Conditions |
| Webhook не срабатывает | Нет custom message для internal-событий | Включить Custom message в операции |
| Remote command не выполняется | Команда не определена в global scripts со scope Action operation | Определить скрипт |
| Эскалация не повторяется | Длительность шага или диапазон шагов заданы неверно; шаг < 60 c | Проверить Steps и step duration |
| Recovery-сообщение не пришло | Recovery operations не настроены; нет получавших problem | Настроить recovery operation |
| Уведомления идут во время maintenance | Снята галочка `Pause operations for suppressed problems` | Вернуть галочку |
| Эскалация «зациклилась» после отключения объекта | Оповещение об отмене | Проверить Notify about canceled escalations; разобрать причину отключения |
| Дубли уведомлений из webhook | Один webhook в нескольких действиях на одно событие | Разделить теги/действия по разным проблемам |

---

## Лучшие практики

* **Несколько уровней эскалации** — дежурный → старший инженер → руководитель; не полагаться на один канал.
* **Custom messages с макросами** (`{EVENT.NAME}`, `{EVENT.SEVERITY}`, `{ESC.HISTORY}`) повышают информативность.
* **Условия строго по тегам/группам**, а не «на всё» — иначе alert fatigue.
* **Recovery-уведомления обязательны** — закрытие инцидента так же важно, как открытие.
* **Maintenance + Pause operations** — не будить дежурного на плановых работах.
* **Remote command применять осторожно** (особенно reboot/restart) — только с осознанными условиями и тестированием.
* **Webhook-теги для трекинга** (ID тикета) — чтобы обновлять/закрывать инцидент во внешней системе.
* **Проверять Action log** после изменений — единственный надёжный способ убедиться в доставке.
* **Разделять severity и маршрутизацию:** Information — в лог, Disaster — звонком.

---

## Дополнительная информация

### См. также

* [Zabbix — лучшие практики настройки](./zabbix_best_practices.md) — стратегия оповещений, подавление, корреляция.
* [Zabbix — триггеры и выражения](./zabbix_triggers.md) — источник problem/OK-событий.
* [Zabbix — пользовательские макросы](./zabbix_macros.md) — макросы в сообщениях и webhook.
* [Zabbix — Inventory и отчётность](./zabbix_inventory_and_reporting.md) — SLA по закрытым проблемам.
* [Zabbix — API и автоматизация](./zabbix_api_automation.md) — управление действиями через API.

### Источники и ссылки

* Zabbix documentation: [Escalations](https://www.zabbix.com/documentation/7.0/en/manual/config/notifications/action/escalations)
* Zabbix documentation: [Operations](https://www.zabbix.com/documentation/7.0/en/manual/config/notifications/action/operation)
* Zabbix documentation: [Recovery operations](https://www.zabbix.com/documentation/7.0/en/manual/config/notifications/action/recovery_operations)
* Zabbix documentation: [Media types](https://www.zabbix.com/documentation/7.0/en/manual/config/notifications/media)
* Zabbix documentation: [Webhook](https://www.zabbix.com/documentation/7.0/en/manual/config/notifications/media/webhook)
