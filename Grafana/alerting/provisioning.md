# Декларативное управление оповещениями — Provisioning

> **Актуальность версий (2026):** Grafana 13.x — текущая стабильная ветка (Current), 12.x — поддержка безопасности (LTS), 11.x — EOL (июнь 2026). В Grafana 13.0+ доступен режим Single-Node Evaluation (SNE, public preview); он включается явно (`ha_single_node_evaluation = true`), по умолчанию отключён. Нативные inhibition rules доступны в beta. DMA-алерты устаревают в Grafana Cloud.

## Определения

**Provisioning (Провиженинг) алертов** — методология Infrastructure as Code (IaC), позволяющая декларативно описывать все компоненты системы оповещений Grafana (правила, контакт-пойнты, политики, шаблоны) через YAML-файлы. Это исключает ручную настройку через UI и обеспечивает воспроизводимость конфигурации в разных окружениях (Dev/Stage/Prod). Актуально для Grafana 12.x и 13.x (проверено август 2026).

> Почему это важно: ручная настройка через UI невоспроизводима, не видна в Git и теряется при пересоздании инстанса. Провиженинг делает конфигурацию алертинга частью репозитория, даёт code review, роллбэк по Git и гарантирует идентичность окружений. Файловый провиженинг **не доступен в Grafana Cloud** — там используется Terraform-провайдер или Alerting provisioning HTTP API.

## Базовые концепции

### Структура директорий

Grafana сканирует директорию `/etc/grafana/provisioning/alerting/` при запуске. Стандартная структура (Grafana 12.x/13.x):

```
/etc/grafana/provisioning/alerting/
├── rules/           # Alerting и Recording rules (группы правил)
├── contactpoints/   # Контакт-пойнты (каналы уведомлений)
├── policies/        # Политики уведомлений (дерево маршрутизации)
├── mute_timings/    # Интервалы подавления (расписания)
├── templates/       # Go-шаблоны уведомлений (группы шаблонов)
└── (опционально)    # Файлы могут лежать и в одной плоской папке
```

**Важные нюансы:**

- **Единый формат файла:** каждый YAML-файл начинается с `apiVersion: 1` и содержит ровно один корневой ключ (`rules`/`contactPoints`/`policies`/`muteTimes`/`templates`/`deleteMuteTimes`/`deleteRules`). Имя файла произвольно, важен корневой ключ.
- **Hot Reload:** Изменения в YAML-файлах подхватываются Grafana «на лету» без перезагрузки сервиса (за исключением глобальных настроек в `grafana.ini`). Перезагрузку также можно инициировать через Grafana Admin API (см. ниже).
- **UID Consistency:** Всегда задавайте статичные `uid` для всех ресурсов. Это предотвращает создание дубликатов при пересоздании контейнеров и сохраняет историю в базе данных. Для контакт-пойнтов `uid` ресивера **не должен превышать 40 символов** и может содержать только латиницу, цифры, `-` и `_`.
- **OrgID:** поле `orgId` (по умолчанию `1`) обязательно для мультитенантных окружений; при его отсутствии ресурс попадает в организацию по умолчанию.
- **Интерполяция переменных:** Используйте `${MY_SECRET}` для токенов. Для этого в `grafana.ini` должна быть включена опция `enable_env_vars_interpolation = true`. Исключения (НЕ интерполируются): `annotations` правил, `relativeTimeRange` правил, `data.model` правил, `name`/`time_intervals` mute timings, `name`/`template` групп шаблонов.
- **Provenance (происхождение):** ресурсы, загруженные из файла, помечаются как `Provisioned` и **не редактируются в UI** — любые правки возможны только в исходном файле с последующим перезапуском/хот-релоадом. Чтобы разрешить редактирование в UI для API-провиженинга, используется заголовок `X-Disable-Provenance: true` (только при API-провиженинге, не при файловом).

### Как работает сканирование и Hot Reload

1. При старте Grafana читает `grafana.ini` → секцию `[paths]` → `provisioning = /etc/grafana/provisioning` и рекурсивно обходит `provisioning/alerting/`.
2. Каждый файл с валидным `apiVersion: 1` применяется: создаются/обновляются ресурсы, совпадающие по `uid`/`name`.
3. Далее Grafana следит за изменениями файлов (file watcher). При правке достаточно сохранить файл — изменения подхватятся автоматически (Hot Reload). Если автоматический перезахват не сработал, принудительная перезагрузка выполняется через Grafana Admin API:

   ```bash
   # Перезагрузить только алертинг
   curl -X POST "http://admin:admin@localhost:3000/api/admin/provisioning/alerting/reload"
   # Или перезагрузить весь провиженинг (включая дашборды/источники)
   curl -X POST "http://admin:admin@localhost:3000/api/admin/provisioning/reload"
   # → 200 OK, если перезагрузка прошла успешно
   ```

4. Провиженинг может **создавать, обновлять и удалять** ресурсы. Удаление ресурса из файла приводит к его удалению из Grafana при следующей загрузке (для mute timings есть явный список `deleteMuteTimes`).

### Что можно провижинить файлом

Grafana поддерживает файловый провиженинг следующих ресурсов (единый набор для `provisioning/alerting`):

| Ресурс | Корневой ключ в YAML | Удаление через файл |
| :--- | :--- | :--- |
| Alert rules (вкл. Recording rules) | `rules` | удаление из файла |
| Contact points | `contactPoints` | удаление из файла |
| Notification policies (всё дерево) | `policies` | перезапись всего дерева |
| Mute timings | `muteTimes` | `deleteMuteTimes` |
| Notification template groups | `templates` | удаление из файла |

**Дополнительные ключи для удаления:**

| Ресурс | Ключ для удаления | Примечание |
| :--- | :--- | :--- |
| Alert rules | `deleteRules` | Явный список UID для удаления (аналогично `deleteMuteTimes`) |
| Notification templates | `deleteTemplates` | Явный список имён шаблонных групп |

> **Тишины (Silences) и правила подавления (Inhibition Rules) НЕ являются файловыми ресурсами.** Они создаются в рантайме: Silences — через UI (Alerting → Silences) или Alerting provisioning HTTP API; Inhibition Rules настраиваваются во встроенном Alertmanager через UI/API. Теоретические основы — в [Основных концепциях](../alerting/concepts.md).

### Миграция DMA → GMA (Data Source-managed → Grafana-managed)

Grafana поддерживает два типа алерт-правил. С точки зрения провиженинга, важно понимать разницу:

| Тип | Где хранятся правила | Провиженинг через Grafana |
| :--- | :--- | :--- |
| **Grafana-managed (GMA)** | Внутренняя БД Grafana | Да, через `rules` в `provisioning/alerting` |
| **Data source-managed (DMA)** | В самом источнике (Prometheus/Mimir/Loki) | Нет — управляется через `rules` источника или Mimir/Cortex tooling |

**DMA устаревает (Grafana Cloud, 2026):** в новых стеках DMA-алерты по умолчанию не создаются. Импортируйте существующие DMA-правила в GMA через инструмент импорта (`Import data source-managed alerts`), чтобы они стали частью Grafana-провиженинга. Подробности — в [concepts.md](../alerting/concepts.md), раздел «Источники данных».

---

## Правила (Alerting и Recording Rules)

### Техническая структура правила (`data`)

Поле `data` представляет собой массив объектов, описывающих конвейер обработки данных (см. конвейер выражений в [concepts.md](../alerting/concepts.md)).

| Поле | Описание |
| :--- | :--- |
| `refId` | Идентификатор шага (например, `A`, `B`, `C`). |
| `datasourceUid` | UID источника данных или `__expr__` для вычислительных шагов. |
| `model` | Объект с параметрами запроса или выражения. |
| `queryType` | Опционально: тип запроса источника (например, `randomWalk` для testdata). |
| `relativeTimeRange` | Окно оценки для шага запроса (например, `from: 600, to: 0` — последние 10 мин). |

**Параметры `model` для запросов (Query):**

- `expr`: Строка запроса (PromQL, LogQL, SQL).
- `instant`: `true/false` (для Prometheus/Mimir).
- `format`: `time_series` или `table`.
- `legend` / `legendFormat`: шаблон имени серии (для дашбордов/чтения).

**Параметры `model` для выражений (Expression):**

- `type`: `math` (математика), `reduce` (агрегация), `resample` (изменение окна), `threshold` (порог).
- `conditions`: Массив условий для типа `threshold`.
- `reducer`: функция агрегации для `reduce` (`last`, `mean`, `max`, `min`, `sum`, `count`).
- `expression`: ссылка на предыдущий `refId` (например, `A`).

**Ключевые поля верхнего уровня правила:**

| Поле | Описание |
| :--- | :--- |
| `uid` | Уникальный идентификатор (статичный, для идемпотентности). |
| `title` | Человекочитаемое имя алерта. |
| `condition` | `refId` последнего шага конвейера, определяющего сработку (например, `C`). |
| `for` | Задержка до перехода в `Alerting` (снижает дребезг). |
| `keep_firing_for` | Удерживать алерт в `Firing` после возврата метрики в норму (например, `5m`). Предотвращает `flapping`. |
| `noDataState` | Поведение при пустом результате: `NoData` / `Alerting` / `OK`. |
| `execErrState` | Поведение при ошибке: `Error` / `Alerting` / `OK`. |
| `folder` / `folderUid` | Папка Grafana, в которой живёт группа правил. |
| `orgId` | Идентификатор организации (по умолчанию `1`). |
| `labels` | Метки для маршрутизации (см. [concepts.md](../alerting/concepts.md)). |
| `annotations` | Аннотации для людей (summary, description, runbook_url). |

### Пример: Alerting Rule с конвейером выражений

```yaml
# provisioning/alerting/rules/app-alerts.yaml
apiVersion: 1
groups:
  - orgId: 1
    name: "Application Alerts"
    folder: "Production"
    folderUid: "prod-folder"
    interval: 1m
    rules:
      - uid: high_error_rate_api
        title: "High Error Rate API"
        condition: C
        for: 5m
        keep_firing_for: 5m
        noDataState: NoData
        execErrState: Error
        labels:
          severity: critical
          team: backend
        annotations:
          summary: "Высокая доля ошибок на {{ $labels.instance }}"
          description: "Доля ошибок: {{ $values.B.Value }}%"
        data:
          - refId: A
            datasourceUid: prometheus_prod
            queryType: ""
            relativeTimeRange:
              from: 600
              to: 0
            model:
              expr: "sum(rate(http_errors_total[5m]))"
              format: time_series
          - refId: B
            datasourceUid: "__expr__"
            model:
              type: reduce
              reducer: last
              expression: A
          - refId: C
            datasourceUid: "__expr__"
              model:
                type: math
                expression: "$B > 10"
```

> **Важно:** `condition` должен ссылаться на последний осмысленный шаг. Если использовать `threshold` вместо `math`, шаг типа `threshold` сам формирует булев результат и указывается в `condition`.

### Пример: Recording Rule (Нативный провиженинг)

Recording Rules позволяют вычислять метрики на стороне Grafana и записывать их обратно в источник.

```yaml
      - uid: node_cpu_usage_avg
        title: "node:cpu_usage:avg5m"
        record:
          metric: "node:cpu_usage:avg5m"
          # для Grafana-managed recording rule результат пишется в выбранный
          # совместимый бэкенд (Mimir/Prometheus) через Remote Write
        data:
          - refId: A
            datasourceUid: mimir_ds
            model:
              expr: "avg(rate(node_cpu_seconds_total[5m]))"
```

> **Grafana-managed vs Data source-managed:** запись через `record` в файле провиженинга создаёт Grafana-managed recording rule (вычисляется сервером Grafana). Для data source-managed (Mimir/Loki/Prometheus Ruler) правила вычисляются на стороне бэкенда и управляются его собственным инструментарием (Mimir/Cortex tooling), а не файлами Grafana (см. [concepts.md](../alerting/concepts.md)).

---

## Контакт-пойнты (Contact Points)

Декларативная настройка каналов уведомлений. В Grafana 12.x/13.x поддерживаются расширенные настройки безопасности и форматирования.

### Настройка Webhook и Kafka

```yaml
# provisioning/alerting/contactpoints/receivers.yaml
apiVersion: 1
contactPoints:
  - orgId: 1
    name: "Internal-Webhook"
    receivers:
      - uid: cp_webhook_01
        type: webhook
        disableResolveMessage: false   # не слать отдельное уведомление о восстановлении
        settings:
          url: "https://alerts.internal.net/api/receive"
          httpMethod: "POST"
          maxAlerts: 10
          authorization:
            type: "Bearer"
            credentials: ${WEBHOOK_TOKEN}
  - name: "Kafka-Topic"
    receivers:
      - uid: cp_kafka_01
        type: kafka
        settings:
          restProxyUrl: "http://kafka-rest:8082"
          topic: "monitoring-events"
          # Включение скриншота через встроенный Image Renderer
          uploadImage: true
```

> **Длина `uid`:** не более 40 символов, только `A-Za-z0-9_-`. Превышение лимита — типичная ошибка валидации при загрузке.

### Настройка Telegram и Slack

Для детальной настройки Telegram (создание бота, получение Chat ID, шаблонизация MarkdownV2) см. специализированное руководство:

- **[Интеграция с Telegram](../alerting/telegram-integration.md)** — основной источник по теме.

Пример настройки Slack (кратко):

```yaml
  - name: "Slack-Alerts"
    receivers:
      - uid: cp_slack_01
        type: slack
        disableResolveMessage: false
        settings:
          recipient: "#monitoring"
          token: ${SLACK_TOKEN}
          # можно задать кастомный шаблон заголовка/тела:
          # title: '{{ template "team.subject" . }}'
          # message: '{{ template "team.message" . }}'
```

---

> **Через Helm values (kube-prometheus-stack).** В стеке kube-prometheus-stack контакт-пойнты можно задать напрямую в `values.yaml` через ключ `grafana.alerting.contactpoints.yaml` — он рендерится в файл провиженинга `provisioning/alerting/contactpoints.yaml`. Подробнее: [Конфигурация Grafana в kube-prometheus-stack](../Prometheus/kubernetes/Kube_Prometheus_Stack_Helm/grafana_config.md#сценарий-8-провижининг-источников-данных-и-контакт-пойнтов-через-additionaldatasources).

## Шаблоны уведомлений (Templates)

Группы Go-шаблонов выносятся в отдельный файл и могут переиспользоваться во многих контакт-пойнтах. Один файл содержит ключ `templates` — список групп, каждая со своим `name` и телом `template` (внутри — директивы `{{ define "..." }}`).

```yaml
# provisioning/alerting/templates/notify-templates.yaml
apiVersion: 1
templates:
  - name: team_templates
    template: |
      {{ define "team.subject" }}[{{ .Status | toUpper }}] {{ .CommonLabels.alertname }}{{ end }}

      {{ define "team.message" }}
      {{ len .Alerts }} алерт(ов):
      {{ range .Alerts }}
      - severity={{ .Labels.severity }} instance={{ .Labels.instance }}
        {{ .Annotations.summary }}
      {{ end }}
      {{ end }}
```

Подключение в контакт-пойнте выполняется по имени определённого шаблона (`{{ template "team.message" . }}`), как показано в примере Slack выше. Доступные объекты: `.CommonLabels`, `.CommonAnnotations`, `.Alerts`, `.Status` (см. [concepts.md](../alerting/concepts.md), раздел «Шаблоны уведомлений»). Ошибка в шаблоне ломает доставку уведомления этому контакт-пойнту.

---

## Политики уведомлений (Маршрутизация)

Политики определяют, как алерты распределяются по контакт-пойнтам с использованием **Label Matching**. В Grafana всё дерево политик — **единый ресурс**: оно целиком задаётся в одном файле и при перезагрузке **полностью перезаписывается**. Частично (отдельной веткой) провижинить дерево нельзя — любая правка требует указания всего дерева, начиная с корня (`receiver: grafana-default`).

### Использование object_matchers

```yaml
# provisioning/alerting/policies/routing.yaml
apiVersion: 1
policies:
  - orgId: 1
    receiver: "default-receiver"
    group_by: ["alertname", "cluster"]
    group_wait: 30s
    group_interval: 5m
    repeat_interval: 4h
    routes:
      - receiver: "critical-oncall"
        object_matchers:
          - ["severity", "=", "critical"]   # Точное совпадение
          - ["env", "=~", "prod.*"]         # Регулярное выражение
        group_wait: 10s
        continue: true                      # Продолжить поиск по «братьям» родителя
        routes:                             # Вложенная политика (наследует group_by/тайминги)
          - receiver: "db-oncall"
            object_matchers:
              - ["service", "=", "database"]
      - receiver: "team-slack"
        object_matchers:
          - ["team", "=~", "backend|frontend"]
        mute_time_intervals:                # ссылка на Mute Timing по имени
          - "Maintenance-Window"
```

**Ключевые особенности:**

- **`object_matchers`** — рекомендуемый Grafana-формат матчеров: список троек `[метка, оператор, значение]`. Альтернатива — Prometheus-формат `matchers` (строки вида `severity = critical`, `severity =~ "warning|critical"`); Grafana поддерживает оба, но `object_matchers` надёжнее при сложных метках.
- **Операторы:** `=` (точное), `!=` (не равно), `=~` (regex), `!~` (regex not).
- **Наследование:** дочерняя политика наследует `group_by` и тайминги родителя, если не переопределены.
- **`continue: true`** — позволяет алерту матчиться также с «братьями» родителя (по умолчанию выключено: один алерт → одна политика).
- **`override_grouping` / `override_general_timings`** — в дочерней политике можно явно переопределить `group_by` и тайминги родителя, не наследуя их.
- **`active_time_intervals`** — противоположный Mute Timing механизм: уведомления подавляются, **если** время НЕ попадает в интервал (алертит только в указанные окна). Mute Timing имеет приоритет над Active time interval при пересечении.
- **`mute_time_intervals`** — список имён Mute Timings; корневая политика (`receiver: grafana-default`) **не может** иметь mute times.
- **`group_by: ['...']`** — специальное значение: отключает агрегацию (каждый алерт — отдельное уведомление); используйте только при очень низком объёме.
- Провиженинг дерева перезаписывает **все** политики, но не затрагивает внутренние политики, созданные когда правило напрямую выбирает contact point.

### Single-Node Evaluation (SNE) и провиженинг

В Grafana 13.0+ доступен **SNE** (public preview). При явном включении (`ha_single_node_evaluation = true`) алерты оцениваются одним инстансом (Primary, позиция 0), остальные инстансы вычисление пропускают. Это упрощает провиженинг: не нужно думать о согласовании `Leader` через Memberlist, конфликтующих обновлениях и синхронизации state между узлами. По умолчанию режим отключён. Подробности — в [Grafana: Высокая доступность](../high_availability.md).

> **Для классического HA (Grafana 12.x и ниже):** провиженинг-файлы должны быть идентичны на всех инстансах, иначе Leader-узел перезапишет конфигурацию других. Используйте `Provisioned`-метку и проверяйте `orgId`/`uid` на соответствие.

---

## Интервалы подавления (Mute Timings)

Mute Timing привязывает именованное расписание (Time Interval) к политике уведомлений — в указанные окна уведомления не доставляются (см. теорию в [concepts.md](../alerting/concepts.md)).

```yaml
# provisioning/alerting/mute_timings/schedules.yaml
apiVersion: 1
muteTimes:
  - orgId: 1
    name: "Maintenance-Window"
    time_intervals:
      - weekdays: ["monday"]
        times:
          - start_time: "02:00"
            end_time: "04:00"
        location: "UTC"
  - name: "no-weekends"
    time_intervals:
      - weekdays: ["saturday", "sunday"]
        location: "Europe/Moscow"
  - name: "q1-freeze"
    time_intervals:
      - months: ["1:3"]          # диапазон месяцев
        days_of_month: ["1:5"]   # диапазон дней месяца
        years: ["2026"]
        location: "UTC"
```

**Удаление** Mute Timing выполняется явным списком `deleteMuteTimes` (простое удаление из файла не сработает для этого ресурса):

```yaml
apiVersion: 1
deleteMuteTimes:
  - orgId: 1
    name: "Maintenance-Window"
```

> **Time Interval** поддерживает: `weekdays` (в т.ч. диапазоны `monday:friday`), `times` (окна `start_time`/`end_time`), `days_of_month`, `months`, `years`, `location` (IANA-таймзона). Сам по себе интервал не глушит — он применяется через `mute_time_intervals` в политике.

---

## Взаимодействие с Kubernetes и AlertmanagerConfig

Важно разделять сферу ответственности при работе в Kubernetes:

1. **AlertmanagerConfig (CRD):** Это ресурс Prometheus Operator. Он управляет конфигурацией *внешнего* Alertmanager (того, который идет в комплекте с kube-prometheus-stack).
2. **Grafana Alerting Provisioning:** Управляет *внутренним* Alertmanager Grafana.

**Можно ли управлять AlertmanagerConfig через провиженинг Grafana?**
Нет. `AlertmanagerConfig` — это объект Kubernetes, он создается через манифесты `kubectl` или Helm. Grafana Provisioning работает только с внутренними файлами Grafana.

**Как их связать?**
Если вы используете `AlertmanagerConfig` для настройки внешнего Alertmanager, вы можете через провиженинг Grafana настроить **Data Source** (Prometheus), чтобы он отправлял свои алерты именно туда, или использовать внешний Alertmanager в качестве основного бэкенда для уведомлений в настройках Grafana Alerting (контакт-пойнт типа `prometheus-alertmanager` с `url` внешнего Alertmanager).

---

## Практические сценарии

> Ниже — прикладной, воспроизводимый путь развёртывания провиженинга. Теория конвейера выражений, состояний и жизненного цикла — в [concepts.md](../alerting/concepts.md).

### Предварительные требования

- **Grafana:** 12.x или 13.x (OSS или Enterprise); **не Grafana Cloud** для файлового провиженинга.
- **Доступ к файловой системе:** монтированная директория провиженинга (`/etc/grafana/provisioning/alerting`) — локально, в Docker-томе или через sidecar (Helm chart kube-prometheus-stack / grafana).
- **`grafana.ini`:** для интерполяции секретов включить `[security]` → `enable_env_vars_interpolation = true`.
- **Секреты:** переменные окружения (`${SLACK_TOKEN}`, `${WEBHOOK_TOKEN}`) заданы в окружении процесса Grafana (в Docker — `environment:`, в systemd — `Environment=`, в Helm — `env` в values).
- **Права:** пользователь Grafana с ролью Admin (для просмотра/экспорта и вызова Admin API reload).
- **Источники данных:** уже настроены и доступны (совпадающие `datasourceUid`).

### Сценарий 1. Развёртывание провиженинга через Git + Docker

1. Создайте структуру в репозитории:

   ```
   grafana/provisioning/alerting/
   ├── rules/app-alerts.yaml
   ├── contactpoints/receivers.yaml
   ├── policies/routing.yaml
   ├── mute_timings/schedules.yaml
   └── templates/notify-templates.yaml
   ```

2. Заполните файлы (примеры выше), задав статичные `uid` и `orgId: 1`.
3. При запуске Docker смонтируйте том (read-only рекомендуется):

   ```bash
   docker run -d --name grafana \
     -e SLACK_TOKEN=${SLACK_TOKEN} \
     -e WEBHOOK_TOKEN=${WEBHOOK_TOKEN} \
     -e GF_SECURITY_ENABLE_ENV_VARS_INTERPOLATION=true \
     -v $(pwd)/grafana/provisioning:/etc/grafana/provisioning:ro \
     -p 3000:3000 grafana/grafana:13.0
   # → Grafana при старте прочитает файлы и создаст ресурсы
   ```

4. В логах Grafana проверьте отсутствие ошибок провиженинга:

   ```bash
   docker logs grafana 2>&1 | grep -i "alerting.*provision\|error.*provision"
   # → ошибок быть не должно; успешная загрузка логируется без исключений
   ```

5. Откройте UI: **Alerting → Alert rules / Notification policies / Contact points** — ресурсы помечены `Provisioned`.
6. Для применения правок без перезапуска контейнера выполните Hot Reload через Admin API:

   ```bash
   curl -X POST "http://admin:admin@localhost:3000/api/admin/provisioning/alerting/reload"
   # → 200 OK
   ```

### Сценарий 2. Полное дерево маршрутизации в одном файле

Поскольку дерево политик — единый ресурс, при добавлении новой ветки (например, для команды `sre`) нужно переписать весь файл `policies/routing.yaml`, сохранив корень и существующие `routes`, и добавить новую:

```yaml
apiVersion: 1
policies:
  - orgId: 1
    receiver: "default-receiver"
    group_by: ["alertname", "cluster"]
    group_wait: 30s
    group_interval: 5m
    repeat_interval: 4h
    routes:
      - receiver: "critical-oncall"
        object_matchers:
          - ["severity", "=", "critical"]
        continue: true
      - receiver: "team-slack"
        object_matchers:
          - ["team", "=~", "backend|frontend"]
      - receiver: "sre-pager"
        object_matchers:
          - ["team", "=", "sre"]
        mute_time_intervals:
          - "no-weekends"
```

После сохранения — Hot Reload (см. Сценарий 1, шаг 6). Старая ветка `critical-oncall` сохраняется, так как она явно присутствует в файле.

### Сценарий 3. CI/CD: провиженинг через GitOps + валидация

Для SRE-команд важен путь: код → проверка → депloy. Пример pipeline:

```yaml
# .github/workflows/alerting-provisioning.yml (упрощённо)
name: Alerting Provisioning
on:
  push:
    paths: ['grafana/provisioning/alerting/**']

jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: YAML lint
        run: |
          pip install yamllint
          yamllint -d relaxed grafana/provisioning/alerting/
      - name: Проверка uid длины
        run: |
          grep -rE 'uid:\s*["\']?[a-zA-Z0-9_-]{41,}' grafana/provisioning/alerting/ \
            && echo "ERROR: uid > 40 chars" && exit 1 \
            || echo "OK: all uids <= 40 chars"
  deploy:
    needs: validate
    runs-on: ubuntu-latest
    steps:
      - name: Hot Reload через Admin API
        run: |
          curl -X POST "http://admin:${{ secrets.GRAFANA_ADMIN_TOKEN }}@grafana.internal/api/admin/provisioning/alerting/reload"
          # → 200 OK
```

**Ключевые моменты:**
- `yamllint` ловит синтаксис до деплоя.
- Проверка длины `uid` предотвращает `failed to validate` на Grafana.
- Hot Reload через Admin API — без перезапуска контейнера.
- Секреты (`GRAFANA_ADMIN_TOKEN`, `${SLACK_TOKEN}`) хранятся в Secrets, не в репозитории.

### Проверка корректности (Validation)

- **Статус ресурсов:** UI показывает метку `Provisioned` у провиженинных правил/политик/контакт-пойнтов.
- **Оценка правила:** **Alerting → Alert rules** — состояние `Normal`/`Pending`/`Alerting` и время последней оценки. В редакторе кнопка **Preview** показывает число экземпляров и значения.
- **Экспорт для сверки:** `GET /api/v1/provisioning/policies/export?format=yaml` возвращает текущее дерево в формате файла — можно сравнить с исходником.
- **Тест контакт-пойнта:** на странице Contact point нажмите **Test** — должно прийти тестовое сообщение с ожидаемым шаблоном (проверяет корректность `settings` и Go-шаблона).
- **Доставка:** во время `Alerting` проверьте канал (Slack/Telegram) и `Alerting → Silences/Notifications`.
- **Логи:** при ошибках провиженинга Grafana пишет в `logger=provisioning` / `logger=alerting`; `execErrState: Error` у правила виден в UI как состояние `Error`.

### Устранение неполадок (Troubleshooting)

| Симптом | Вероятная причина | Решение |
| :--- | :--- | :--- |
| Ресурс не появился после правки файла | Hot Reload не сработал / файл вне `provisioning/alerting` | Вызовите Admin API reload; проверьте путь и `apiVersion: 1` |
| `failed to load provisioning` / YAML parse error | Синтаксическая ошибка YAML, табуляция вместо пробелов | Прогоните `yamllint`/валидатор; используйте 2 пробела |
| `uid ... should not exceed 40 symbols` | Слишком длинный `uid` ресивера контакт-пойнта | Сократите `uid` до ≤40 символов (`A-Za-z0-9_-`) |
| Контакт-пойнт не шлёт, но тест работает | Неверная маршрутизация / активная Mute Timing / тишина | Проверьте `object_matchers` политики, `mute_time_intervals`, Silences |
| Уведомление «пустое»/без полей | Ошибка Go-шаблона в `templates` или `settings` | Проверьте синтаксис шаблона; валидируйте через **Test** |
| `${TOKEN}` не подставился | `enable_env_vars_interpolation` выключен или переменная не в окружении Grafana | Включите опцию в `grafana.ini`; задайте переменную в окружении процесса |
| Дерево политик «сбросилось» | Перезапись всего дерева при правке одной ветки | Всегда держите полное дерево в файле; не правьте ветки по отдельности |
| `Provisioned` ресурс нельзя редактировать в UI | Ожидаемое поведение файлового провиженинга | Правьте файл и делайте reload (для UI-правок — только API с `X-Disable-Provenance`) |
| В Grafana Cloud файлы игнорируются | Файловый провиженинг недоступен в Cloud | Используйте Terraform-провайдер или Alerting HTTP API |

### Граничные случаи (Edge Cases)

- **Перезапись всего дерева политик:** правка любой ветки требует хранения полного дерева в файле; иначе неупомянутые ветки удалятся.
- **Удаление Mute Timing:** простое удаление из `muteTimes` не удаляет ресурс — нужен явный `deleteMuteTimes`.
- **Удаление правил/шаблонов:** аналогично — простое удаление из `rules`/`templates` не удаляет ресурс, если он был создан через API/UI; используйте `deleteRules` / `deleteTemplates`.
- **Совпадение `name` Mute Timing с `mute_time_intervals`:** несуществующее имя в политике не глушит и не падает, но тишин не даёт — проверяйте имена.
- **Временные зоны:** `location` в Time Interval задаёт таймзону расписания; несовпадение с локальным временем команды — частый источник «почему ночью пришло уведомление».
- **Интерполяция не применяется** к `annotations`, `relativeTimeRange`, `data.model` правил и к `name`/`time_intervals`/`template` шаблонов и mute timings — секреты в этих полях не подставятся.
- **`orgId` при мультитенантности:** ресурс без `orgId` попадёт в орг. по умолчанию; пересечение `uid` между оргами безопасно (изоляция по org).
- **Grafana Cloud:** файловый провиженинг не работает — единственный путь IaC там: Terraform (`grafana` provider) или Alerting provisioning HTTP API.
- **SNE + провиженинг (Grafana 13+):** Leader-узел применяет провиженинг-файлы; follower-инстансы не трогаются. Не нужно синхронизировать файлы между инстансами.
- **Классический HA (Grafana 12.x):** все инстансы должны иметь одинаковые провиженинг-файлы — Leader перезапишёт конфигурацию при следующем reload.

### Мониторинг провиженинга (Provisioning Monitoring)

Для SRE-сценариев важно отслеживать, что провиженинг работает корректно:

- **Логи:** `logger=provisioning` — ошибки загрузки YAML, конфликты `uid`, провалы Hot Reload. Проверяйте при старте и после правки:
  ```bash
  docker logs grafana 2>&1 | grep -i "logger=provisioning"
  ```
- **Состояние ресурсов:** UI → **Alerting → Alert rules / Contact points / Notification policies** — провиженинные ресурсы помечены `Provisioned`. Отсутствие метки — ресурс создан вручную (не из файла).
- **Экспорт для сверки:** `GET /api/v1/provisioning/alert-rules/export?format=yaml` возвращает все правила в формате provisoning-файла — можно сравнить с Git-источником.
- **Admin API статус:** `GET /api/admin/provisioning` — статус последней перезагрузки (успех/ошибка, метка времени).
- **Alert на сбой провиженинга:** создайте правило с `execErrState: Alerting` и condition `A` на `testdata` — или используйте Grafana Alerting, чтобы отслеживать логи провиженинга через Loki (если Loki настроен как источник).

### Лучшие практики и очистка (Best Practices & Cleanup)

- Задавайте **статичные `uid`** всем ресурсам — это делает провиженинг идемпотентным и сохраняет историю при пересоздании инстанса.
- Храните провиженинг в **Git**, один файл на логический ресурс/группу; проверяйте изменения через code review.
- Делайте том провиженинга **read-only** (`ro`), чтобы случайная правка на диске не меняла конфиг.
- Держите **всё дерево политик в одном файле** и версионируйте его целиком.
- Используйте **`${ENV}`** для секретов, не коммитьте токены в репозиторий.
- Проверяйте контакт-пойнты кнопкой **Test** перед продакшеном; упаковывайте общие шаблоны в `templates/`.
- **Очистка:** удаляйте устаревшие правила/контакт-пойнты из файлов (они удалятся при reload); для Mute Timings — используйте `deleteMuteTimes`, для правил — `deleteRules`, для шаблонов — `deleteTemplates`. Регулярно пересматривайте дерево политик, чтобы не накапливались «мёртвые» ветки. Перед массовыми изменениями экспортируйте текущее состояние (`/api/v1/provisioning/.../export`) как бэкап.
- **DMA → GMA:** планируйте миграцию через инструмент импорта Grafana, чтобы все правила стали GMA и управлялись через провиженинг.
- **CI/CD:** добавьте в CI валидацию YAML (`yamllint`) и проверку `uid` на длину ≤40 символов перед деплоем.

## Дополнительная информация

**См. также:**

- [Основные концепции Grafana Alerting](../alerting/concepts.md) — архитектура конвейера выражений, состояния, HA, SNE.
- [Best practices по алертингу](../alerting/best_practices.md) — рекомендации по фильтрации шума и настройке `for`/интервалов.
- [Интеграция с Telegram](../alerting/telegram-integration.md) — подробная настройка ботов и скриншотов.
- [Алерты для Kubernetes](../alerting/kubernetes_alerts.md) — готовые правила и примеры recording rules для K8s.
- [Grafana: Высокая доступность](../high_availability.md) — HA-архитектура, SNE, Memberlist, Leader.
- [Рендеринг изображений](../grafana_image_rendering.md) — настройка скриншотов в уведомлениях.
- [Мониторинг как код](../monitoring_as_code.md) — GitOps-подход к провиженинг-файлам.
- [Провиженинг Grafana (общий)](../grafana_provisioning.md) — провиженинг дашбордов и источников данных.
- [Конфигурация Grafana в kube-prometheus-stack](../Prometheus/kubernetes/Kube_Prometheus_Stack_Helm/grafana_config.md) — `grafana.alerting.contactpoints.yaml` через Helm values.
