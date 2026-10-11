# Kibana: Workflows

> **Актуально для:** Kibana 9.4+ (GA; в 9.3 — Preview); дополнения 9.5 отмечены в тексте

Workflows — встроенный в Kibana движок автоматизации: YAML-определение с триггером и цепочкой шагов, выполняемый Kibana без внешнего оркестратора. Заменяет рутинные операции триажа, обогащения алертов и уведомлений.

## Определения

* **Workflow** — YAML-определение автоматизации: метаданные (`name`, `description`, `enabled`, `tags`, `version`), константы (`consts`), входные параметры (`inputs`), объявленные выходы (`outputs`), триггеры (`triggers`), глобальные настройки (`settings`) и шаги (`steps`). Хранится в Kibana как saved object; `name` уникален в пределах Space.
* **Trigger** — событие или условие, запускающее workflow: `manual`, `scheduled`, `alert`, `event-driven`.
* **Step** — отдельная единица работы: запрос к Elasticsearch, вызов Kibana API, работа с Cases, HTTP-запрос или действие через connector.
* **Input / const / context variable** — параметры выполнения: `inputs` передаются при запуске, `consts` — фиксированные значения, output'ы шагов доступны последующим шагам, события триггера — в `event`, данные запуска — в `execution`.
* **Liquid** — шаблонизатор, которым подставляются значения в тела шагов (`{{ inputs.message }}`, `{{ steps.<name>.output }}`).
* **Settings** — блок верхнего уровня, задающий глобальное поведение: таймаут выполнения, часовой пояс, конкурентность, лимит размера вывода шага и политику повторов при ошибках.
* **Execution** — один запуск workflow; имеет ID, статус (см. «Жизненный цикл выполнения»), лог шагов и возможность возобновления (`resume`).

## Основные концепции

### Триггеры

| Тип | Когда срабатывает | Примеры задач |
| :--- | :--- | :--- |
| `manual` | По действию пользователя (UI) или API | Тесты, разовые операции, действие «по кнопке» |
| `scheduled` | По интервалу или RRule-выражению | Ежедневные отчёты, очистка данных, health-check |
| `alert` | При срабатывании detection/alerting rule (контекст алерта передаётся в workflow) | Триаж и обогащение алертов, создание Cases, маршрутизация |
| `event-driven` | При событии платформы | Обработка падения другого workflow (`workflows.failed`), изменение Cases, lifecycle правил (experimental) |

* Интервал scheduled-триггера: минимум **1 минута** (`1m`/`60s`); более короткие значения отклоняются при сохранении. Расписания с подминутным интервалом из 9.3 автоматически мигрируются в `1m` при первом редактировании. Единицы: `s` (минимальное значение `60s`), `m`, `h`, `d`.
* RRule-расписание: поддерживаемые `freq` — только `DAILY`, `WEEKLY`, `MONTHLY`; `HOURLY`, `MINUTELY`, `YEARLY`, `SECONDLY` отклоняются (для почасового расписания используйте интервал `every: 1h`). Обязательны `freq`, `interval`, `tzid`; при `WEEKLY` обязателен `byweekday` (`MO`…`SU`), при `MONTHLY` — `bymonthday` (допустимы отрицательные значения, `-1` — последний день месяца). Необязательны `dtstart`, `byhour`, `byminute`. Часовой пояс — IANA-идентификатор (`Europe/Moscow`); задавайте `tzid` явно, чтобы переход на летнее время не сдвигал запуск.
* Scheduled-workflow выполняются **с привилегиями пользователя, последним сохранившего workflow** — это определяет, к каким данным/пространствам будет доступ (полная таблица — в разделе «Авторизация выполнения»).
* Event-driven-семейства и их статусы: `workflows.failed` — GA с 9.5 (Preview в 9.4); Cases-triggers (`cases.caseCreated`, `cases.caseUpdated`, `cases.caseStatusUpdated`, `cases.attachmentsAdded`, `cases.commentsAdded`) и entity store-триггеры (`entityStore.entityAssetCriticalityUpdated`, `entityStore.entityRiskScoreChanged`) — Preview с 9.5; lifecycle триггеры экспериментальной системы алертинга (`alerting.episode*`, `alerting.rule*`) — Experimental с 9.5 и доступны только при включённой экспериментальной системе алертинга (episode-триггеры не описываются блоком `triggers` — workflow привязывается к ним через UI). Фильтрация событий — KQL-условие в `on.condition`.
* Защита от циклов в event-driven цепочках: `on.workflowEvents` — `avoid-loop` (по умолчанию: цикл-гард пропускает срабатывание, если этот workflow уже есть в текущей цепочке событий), `ignore` (не реагировать на события, порождённые самими workflow), `allow-all` (снять гард; глубина цепочки всё равно ограничена) — GA с 9.5. Дополнительно для обработчиков падений — условие `event.workflow.isErrorHandler : false`.
* Контекст триггера попадает в шаги через `event`: `manual` — данные пользователя и переданные параметры; `scheduled` — время запуска и данные расписания; `alert` — полные данные алерта; `event-driven` — семейство-специфичные поля (`event.workflow.*` и `event.error.*` у `workflows.failed`, `event.caseId`/`event.owner` у Cases-триггеров, `event.entityId`/`event.entityType` у entity store).

### Категории шагов

* **Elasticsearch** — named actions, напрямую отображающиеся на ES API (`elasticsearch.search` → `POST /<index>/_search`, `elasticsearch.update`, управление индексами и data streams), плюс generic request для произвольных вызовов REST. Аутентификация — единый API key выполнителя workflow.
* **Kibana** — `kibana.SetAlertsStatus`, `kibana.SetAlertTags` (изменение статусов/тегов detection-алертов), `kibana.request` — произвольный вызов Kibana API.
* **Security** — именованные `security.*`-шаги вместо универсального `kibana.request`: `security.setAlertStatus`, `security.setAlertTags`, `security.assignAlert`, `security.enableRule`, `security.disableRule` и др. (GA с 9.5).
* **Cases** — отдельные типы шагов для создания, поиска, обновления и закрытия Cases, вложений (alerts, observables, comments), назначения и комментариев.
* **Streams** — работа с Observability Streams (Preview с 9.4): получение списка, выборка значимых событий за окно.
* **Entity store** — установка/снятие asset criticality у сущностей Security (Preview с 9.5).
* **Данные** — шаги `data.*`: фильтрация, маппинг, группировка, разбор JSON, regex-извлечение, дедупликация — то, что громоздко и нечитаемо писать Liquid'ом.
* **Составные** (Preview с 9.4) — `workflow.execute` (синхронный вызов: родитель ждёт результат дочернего workflow) и `workflow.executeAsync` (fire-and-forget fan-out). Дочерний execution наследует execution identity родителя; для вызова через `workflow.execute` у дочернего workflow должен быть объявлен блок `outputs`.
* **Внешние системы** — connector-based действия (`type: slack`, `type: jira` + `connector-id` на одном уровне с `type`; имя или raw ID коннектора) и нативный `http`-шаг: либо через `connector-id` (base URL и секреты хранятся в коннекторе), либо напрямую по `url` без коннектора — секреты в YAML не помещайте.
* **Flow control** — `if`, `switch`, `foreach`, `while` (с `loop.break` / `loop.continue`), `wait`, `waitForInput`, `waitForApproval` (Preview с 9.5) и `parallel` (Preview с 9.5; по умолчанию до 5 веток одновременно). Guardrails: `max-iterations` (у `while` по умолчанию 2000, при достижении лимита `on-limit` по умолчанию `continue`, значение `fail` завершает workflow ошибкой), `iteration-timeout`, `branch-timeout`.

### Привилегии и пространства

Доступ контролируется на двух уровнях.

**UI-привилегии** (Stack Management → Roles): каталог **Analytics → Workflows** — `All` (полное управление) или `Read`; точечная настройка отдельных действий — sub-feature privileges (доступны с тира Gold, тир привилегии наследует тир функции). Управляемые workflow (Managed, 9.5) — additive-привилегии **Managed Workflows Actions**: `Read managed workflows`, `Read managed workflow execution`, `Update managed workflows`.

**Route-привилегии API** (`Route required privileges` в OpenAPI каждого маршрута): `workflowsManagement:read`, `workflowsManagement:create`, `workflowsManagement:update`, `workflowsManagement:delete`, `workflowsManagement:execute` (запуск), `workflowsManagement:readExecution` (просмотр выполнений); для managed workflow — `workflowsManagement:managed:read` и `workflowsManagement:managed:readExecution`.

Все API работают в рамках Space; space-вариант пути — `/s/{space_id}/api/workflows/...`. Использование функционала требует соответствующей подписки — актуальный тир смотрите на странице подписок Elastic.

### Авторизация выполнения

Чьи привилегии действуют при каждом запуске, определяет тип триггера:

| Тип триггера | Чьи привилегии используются |
| :--- | :--- |
| `manual` (UI или API) | Пользователь, запустивший выполнение; сохранённый API key не используется |
| `scheduled` | Пользователь, последний сохранивший workflow |
| `alert` / detection rule | Пользователь, последний сохранивший правило |
| event-based | Пользователь, чьё действие породило событие (например, добавивший комментарий к Case) |
| `workflows.failed` | Те же привилегии, с которыми выполнялся упавший workflow |

Механика:

* Все `kibana.*` и `elasticsearch.*` шаги внутри одного запуска делят **один API key** — отдельного креда на тип шага нет. Шаг падает с ошибкой привилегий, если у исполняющего пользователя не хватает права (например, `createCase` без привилегий Cases).
* Connector-шаги аутентифицируются **собственными кредами коннектора**, а не ключом workflow; для аудита выполнение всё равно записывается под ключом workflow.
* Сохранённый ключ обновляется только двумя способами: пересохранить workflow нужным пользователем либо переключить `enabled` off → on. Деактивация пользователя или изменение его роли ключ автоматически **не** обновляет — старый продолжает работать до пересохранения.
* Identity выполнения фиксируется при старте и виден во вкладке Executions; фильтр «Created By» в списке workflow показывает того, кто сохранил последним, а не первоначального автора.
* Типы ошибок: (1) *step-level privileges error* — прямо на провалившемся шаге во вкладке Executions → сохранить workflow пользователем с нужной ролью; (2) *устаревший/удалённый API key* — ошибка API key на конкретном `elasticsearch`/`kibana` шаге, отдельного статуса или списка для этого состояния нет → refresh через пересохранение или toggle `enabled`.

### Настройки выполнения (`settings`)

Блок верхнего уровня; все поля опциональны, без них действуют дефолты движка.

| Поле | Назначение |
| :--- | :--- |
| `timeout` | Максимальное wall-clock время всего выполнения (`5s`, `10m`, `2h`); по истечении — отмена, статус `timed_out` |
| `timezone` | IANA-пояс по умолчанию для scheduled-расписаний (без `tzid`) и `date`-фильтра Liquid; `rrule.tzid` перебивает |
| `concurrency` | Политика при пересечении выполнений одной группы (см. ниже) |
| `max-step-size` | Потолок размера вывода одного шага (например `10mb`); дефолт задан на уровне деплоя, поле переопределяет его для workflow |
| `on-failure` | Глобальная политика ошибок для всех шагов — та же форма, что у поштучного `on-failure`: `retry: { max-attempts: 2, delay: "10s" }` |

`timeout` включает в себя паузы `wait` и `waitForInput`; срабатывание пошлёт шагам cancel-сигнал (HTTP- и ES-шаги останавливаются быстро, часть шагов может доработать краткое время). Для human-in-the-loop workflow, ожидающих ответа неограниченно, `timeout` не задавайте вовсе или ставьте щедрое значение (например `7d`).

**Конкурентность** предотвращает наезды накладывающихся выполнений: burst detection-правил, мутирующих общее состояние шагов (создание Case, счётчик), scheduled-workflow, runtime которых превышает интервал расписания.

* `key` — Liquid-выражение, дающее идентификатор группы; вычисляется в пределах Space, и разные workflow с одинаковым `key` попадают в одну группу.
* `strategy` — обязателен явный выбор: `queue` (каждый запуск выполнится, но не одновременно; FIFO без приоритетов), `drop` (новый запуск отбрасывается, идущий продолжает), `cancel-in-progress` (новый отменяет текущий — свежие данные важнее).
* `max` — максимум одновременных выполнений на группу, дефолт `1`.
* `queue-size` (дефолт `100`) и `queue-ttl` (дефолт `24h`) — глубина и время жизни очереди для стратегии `queue`, GA с 9.5; переполнение или истечение срока переводит запуск в терминальный `skipped`.
* В очереди ожидающие выполнения получают статус `queued` и продвигаются в `pending`, когда освобождается слот.
* **Ловушка:** ключи на основе `event.*` рассчитаны на alert-trigger; при ручном или scheduled-запуске поле может быть пустым, и группа не применяется. Для workflow со смешанными триггерами используйте ключ от `{{ inputs.* }}` или статический ключ.

```yaml
settings:
  timeout: "10m"
  timezone: "America/Los_Angeles"
  max-step-size: "10mb"
  concurrency:
    key: "{{ event.alerts[0].host.name }}"
    strategy: drop
    max: 1
  on-failure:
    retry:
      max-attempts: 2
      delay: "10s"
```

### Жизненный цикл выполнения

| Статус | Значение |
| :--- | :--- |
| `queued` | Ожидает слот в очереди конкурентности (9.5+) — в отличие от `pending` |
| `pending` | Запланирован, ожидает старта |
| `running` | Выполняется хотя бы один шаг |
| `waiting` | Пауза на шаге `wait`; вернётся в `running` по таймеру |
| `waiting_for_input` | Пауза на `waitForInput`; вернётся в `running` после ответа |
| `waiting_for_child` | Ожидание дочернего workflow, вызванного через `workflow.execute` |
| `completed` | **Терминальный:** успешно завершён |
| `failed` | **Терминальный:** шаг упал и `on-failure` не восстановил выполнение |
| `cancelled` | **Терминальный:** отменён оператором или стратегией конкурентности |
| `timed_out` | **Терминальный:** превышен `settings.timeout` |
| `skipped` | **Терминальный:** отброшен — стратегия `drop` либо переполнение `queue-size`/`queue-ttl` |

Пять терминальных статусов: `completed`, `failed`, `cancelled`, `timed_out`, `skipped`.

## Практические сценарии

### Настройка окружения

* **Kibana 9.3 (Preview):** функция выключена по умолчанию — включите её в **Advanced Settings** (`workflows:ui:enabled`) и перезагрузите страницу. С 9.4 (GA) флаг не нужен.
* **Template library** (Preview с 9.5) выключена по умолчанию; включение — запросом из Dev Tools (внутренний API, может измениться; настройка глобальная, действует на все Spaces):

```http
POST kbn:/internal/kibana/global_settings
{
  "changes": {
    "workflowsManagement:library:enabled": true
  }
}
```

* **Managed workflows** (9.5) скрыты по умолчанию; показать их в списке — Advanced Settings `workflows:ui:showManagedWorkflows` (плюс привилегии Managed Workflows Actions).

### Определение workflow (YAML)

```yaml
name: Daily error digest
description: Собирает ошибки за сутки и отправляет в Slack
enabled: true
tags: ["production", "sre"]

consts:
  indexName: "logs-*"
  alertThreshold: 100

inputs:
  - name: environment
    type: string
    required: true
    default: "staging"
    description: "Target environment"

triggers:
  - type: scheduled
    with:
      rrule:
        freq: DAILY
        interval: 1
        tzid: UTC
        byhour: [9]
        byminute: [0]

settings:
  timeout: "30m"
  on-failure:
    retry:
      max-attempts: 2
      delay: "10s"

steps:
  - name: count_errors
    type: elasticsearch.search
    with:
      index: "{{ consts.indexName }}"
      query:
        bool:
          filter:
            - term:
                log.level: "error"
  - name: notify
    type: slack
    connector-id: "sre-alerts"
    with:
      message: "Errors in {{ inputs.environment }}: {{ steps.count_errors.output.hits.total.value }}"
```

Параметры `with` блока передаются как тело или query-параметры соответствующего API; значения подставляются через Liquid. Для операций без named action используется generic request шаг.

Несколько замечаний к структуре:

* **Расположение `inputs`:** на 9.4 и ранее — верхний уровень; с 9.5 (и на Serverless) новые workflow объявляют `inputs` внутри триггера `manual`, существующие top-level определения продолжают работать. Ссылки `{{ inputs.<name> }}` одинаковы в обоих случаях.
* **Типы `inputs`:** `string`, `number`, `boolean`, `choice` (плюс массив `options`), `array` (плюс `minItems`/`maxItems`); `required` по умолчанию `false`, `default` — фолбэк для необязательных полей.
* **`version`** — строка (`"1"`), а не число: значение `1` без кавычек схема отклоняет. Поле нужно движку для форвард-совместимости — вручную его не задавайте.
* **`name`** должен быть уникален в пределах Space; `enabled: false` — штатный kill switch: scheduled-триггеры перестают срабатывать, alert-workflow не реагируют, ручной запуск возвращает ошибку «workflow is disabled».

### Запуск через API

```bash
# Создание workflow из YAML
curl -X POST "${KBN}/api/workflows/workflow" \
  -H "Authorization: ApiKey ${API_KEY}" \
  -H "kbn-xsrf: true" -H "Content-Type: application/json" \
  -d '{"yaml": "name: Example\nenabled: true\ntriggers:\n- type: manual\nsteps: [...]"}'
# → 200, workflow сохранён (YAML валидируется до сохранения)

# Запуск по ID: тело содержит обязательные inputs
curl -X POST "${KBN}/api/workflows/workflow/<workflow-id>/run" \
  -H "Authorization: ApiKey ${API_KEY}" \
  -H "kbn-xsrf: true" -H "Content-Type: application/json" \
  -d '{"inputs": {"message": "hello from the API"}}'
# → {"workflowExecutionId": "exec-a1b2c3d4-e5f6-7890"}

# Мониторинг выполнения
curl -H "Authorization: ApiKey ${API_KEY}" "${KBN}/api/workflows/executions/<executionId>"
# → статус и логи шагов
```

В Console Dev Tools то же самое: `POST kbn:/api/workflows/workflow/<id>/run` с телом `{"inputs": {...}}`.

Заголовок `kbn-xsrf` обязателен для всех POST-запросов. Основные маршруты (полный список и обязательные привилегии — в OpenAPI):

| Маршрут | Назначение |
| :--- | :--- |
| `GET /api/workflows`, `POST /api/workflows/mget` | Список/поиск workflow и выборка по списку ID |
| `GET/POST /api/workflows/workflow`, `GET/PUT/DELETE /api/workflows/workflow/{id}` | Чтение, создание, изменение, удаление одного workflow |
| `POST /api/workflows` | Bulk create — импорт (`{"workflows": [{"yaml": "..."}]}`, опционально `?overwrite=true`) |
| `DELETE /api/workflows` | Bulk delete по `{"ids": [...]}` (до 1000); по умолчанию soft delete, `?force=true` — hard delete |
| `POST /api/workflows/workflow/{id}/run` | Запуск → `{"workflowExecutionId": ...}` |
| `POST /api/workflows/workflow/{id}/clone`, `POST /api/workflows/export` | Клонирование, выгрузка YAML |
| `GET /api/workflows/schema`, `POST /api/workflows/test`, `POST /api/workflows/step/test` | JSON-схема, тест workflow и отдельного шага |
| `GET /api/workflows/workflow/{workflowId}/executions` (+ `/steps`, `POST .../executions/cancel`) | Выполнения конкретного workflow |
| `GET /api/workflows/executions/{executionId}` (+ `/logs`, `/steps`, `/children`, `POST .../resume`, `POST .../cancel`) | Конкретное выполнение: статус, логи, дочерние запуски, возобновление |
| `GET /api/workflows/stats`, `GET /api/workflows/aggs` | Статистика и агрегации по выполнениям |

Импорт и выгрузка — это разные операции: выгрузка `POST /api/workflows/export`, загрузка — bulk create `POST /api/workflows`.

### Типовые сценарии для продакшена

1. **Триаж алертов**: trigger `alert` → шаги `kibana.SetAlertsStatus` / `kibana.SetAlertTags` → создание Case → уведомление в Slack. Закрывает проблему утомления (alert fatigue) без внешнего оркестратора.
2. **Падение automation**: trigger `workflows.failed` с KQL-условием `on.condition: "event.workflow.isErrorHandler : false"` — централизованный обработчик ошибок, исключая сам errorHandler; дополнительно можно фильтровать по `event.workflow.name`, `event.workflow.spaceId`, `event.error.stepName`.
3. **Регулярная отчётность**: trigger `scheduled` (RRule) → агрегация в Elasticsearch → email/Slack; для отчётов дольше интервала расписания — `concurrency: { strategy: cancel-in-progress }`, чтобы не копить очередь.
4. **Синхронизация с тикетной системой**: Cases-triggers → шаги создания/обновления задач Jira/ServiceNow.
5. **Аудит и разрыв цепочек**: rule lifecycle-триггеры (`alerting.ruleCreated` и др., Experimental) — логирование изменений правил; от события к событию workflow предохраняют `on.workflowEvents: avoid-loop`/`ignore` и `isErrorHandler`.

### Оценка применимости

* Workflows выполняются на узлах Kibana — это не замена очередям/оркестраторам для тяжёлых пайплайнов (для данных используйте Ingest pipelines, ES|QL, Logstash).
* Долгие шаги ограничены таймаутами выполнения; при необходимости раскладывайте на несколько workflow и связывайте через `workflows.failed`/executions API.
* Шаблоны и примеры — в официальном репозитории [elastic/workflows](https://github.com/elastic/workflows) (Template Library).

## Troubleshooting

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| 403 на `/api/workflows/workflow/{id}/run` | Нет привилегии `workflowsManagement:execute` или workflow в другом Space | Добавить привилегию в role, использовать space-путь `/s/{space_id}/...` |
| Ошибка валидации при сохранении | Некорректный YAML: неизвестный тип шага/триггера, отсутствует `enabled`/`name` | Проверить схему через `/api/workflows/schema` и `/api/workflows/test` |
| Scheduled-workflow не выполняется | Workflow выключен (`enabled: false`) либо интервал меньше 1 минуты | Включить workflow, увеличить интервал до `1m` и более |
| Scheduled-workflow выполняется без доступа к данным | Выполняется под пользователем последнего сохранения, у которого нет прав | Пересохранить workflow пользователем с нужными привилегиями |
| Event-driven триггер не срабатывает | Событие не соответствует KQL-условию `on.condition`; часть типов событий — Preview/Experimental | Проверить/уточнить условие, учесть статус доступности типа (9.4/9.5) |
| Шаг не находит данные | Неверный индекс/Space, не подставлены `inputs` | Логи выполнения: `/api/workflows/executions/{executionId}/logs` |
| Ручной запуск отвечает «workflow is disabled» | `enabled: false` (kill switch) | Включить workflow; удаление не требуется — ссылки правил не ломаются |
| Execution в статусе `skipped` | Стратегия concurrency `drop` либо переполнение очереди (`queue-size`/`queue-ttl`) | Пересмотреть стратегию и параметры `concurrency` |
| Execution завершился `timed_out` | Сработал `settings.timeout` | Увеличить timeout, ускорить шаги; для HITL-пауз timeout не задавать |
| Ошибка API key на `elasticsearch`/`kibana`-шаге при исправном пользователе | Сохранённый ключ устарел: пользователь деактивирован, его роль изменена, ключ удалён администратором | Refresh: пересохранить workflow или переключить `enabled` off → on |
| Обработчик `workflows.failed` срабатывает на самом себе | Нет фильтра от собственных падений | `on.condition: "event.workflow.isErrorHandler : false"` |
| Event-driven цепочки размножаются (workflow порождает событие, которое его же запускает) | Нет ограничения workflow-порождённых событий | `on.workflowEvents: ignore` (значение по умолчанию — `avoid-loop`, 9.5+), глубина цепочки ограничена движком |
| Пауза `waitForInput` висит вечно, execution держится | Таймаут не задан, ответ не приходит | Ответить через UI/resume API либо отменить выполнение (`POST .../cancel`) |

## Best Practices

* **Версионируйте определения**: YAML экспортируется через `/api/workflows/export` и хранится в Git; деплой — создание/обновление через API в CI. Раскладка по Space — часть конвенции именования (`<domain>--<verb>-<noun>`).
* **Минимальные привилегии**: чей пользователь авторизует запуск — см. таблицу в разделе «Авторизация выполнения»; выдавайте ровно те привилегии, которые нужны шагам, и помните, что scheduled-workflow наследует права последнего сохраняющего.
* **Идемпотентность**: шаги, изменяющие статусы алертов и Cases, должны допускать повторный запуск (workflow может быть перезапущен после сбоя).
* **Таймаут и retry по умолчанию**: задавайте `settings.timeout` и глобальный `on-failure.retry` — зависший шаг не должен держать выполнение вечно, а транзиентный сбой не должен ронять весь workflow.
* **Конкурентность для scheduled и алертов**: runtime длиннее интервала расписания или burst алертов → `settings.concurrency` (`queue`, чтобы не терять запуски; `cancel-in-progress` для health-check'ов, где важен свежий результат).
* **Фильтруйте события**: для `event-driven` триггеров всегда задавайте `on.condition` (KQL), чтобы не обрабатывать все события подряд; защиту от петель (`on.workflowEvents`, `isErrorHandler`) включайте до выхода в прод.
* **Наблюдаемость**: отслеживайте executions и логи шагов (`/executions/{id}/logs`, `stats`/`aggs`), помните пять терминальных статусов; ошибки workflow доступны централизованно через триггер `workflows.failed`.
* **Не дублируйте Alerting**: бизнес-условия остаются в правилах (rules) — workflow реагирует на уже сработавший алерт, а не проверяет данные самостоятельно.

## Дополнительная информация

* **[Kibana: Обзор](./kibana_overview.md)** — место Workflows в стеке, ресурсы.
* **[Alerting: Kibana Alerting и Watcher](../Elasticsearch/elasticsearch_alerting.md)** — правила, connectors, actions, триггеры алертов.
* **[Kibana: Security Solution](./kibana_security_solution.md)** — detection rules, triage, Cases.
* **[Kibana: Cases](./kibana_cases.md)** — устройство инцидентов и их API (шаги Workflows создают и обновляют именно их).
* [Workflows (официально)](https://www.elastic.co/docs/explore-analyze/workflows) — концепции и структура YAML.
* [Triggers (официально)](https://www.elastic.co/docs/explore-analyze/workflows/triggers) — типы триггеров, расписания, контекст события.
* [Workflow settings (официально)](https://www.elastic.co/docs/explore-analyze/workflows/authoring-techniques/settings) — timeout, concurrency, on-failure.
* [Workflow authorization (официально)](https://www.elastic.co/docs/explore-analyze/workflows/authorization) — чьи привилегии авторизуют запуск, refresh API key.
* [Steps (официально)](https://www.elastic.co/docs/explore-analyze/workflows/steps) — каталог шагов и flow control.
* [Event-driven triggers (официально)](https://www.elastic.co/docs/explore-analyze/workflows/triggers/event-driven-triggers) — семейства событий, `on.condition`, `on.workflowEvents`.
* [Workflows API (официально)](https://www.elastic.co/docs/api/doc/kibana/group/endpoint-workflows) — создание, запуск, executions.
