# Правила в Prometheus: Recording и Alerting

В [Prometheus](./overview.md) "правила" (rules) — это набор выражений на языке [PromQL](./concepts/promql/functions.md), которые периодически вычисляются на стороне сервера. Они позволяют автоматизировать создание новых временных рядов и генерацию оповещений.

> **См. также:** [Типы метрик](./concepts/metric_types/overview.md), [Алерты для типов метрик](./concepts/metric_types/alerts.md), [PromQL](./concepts/promql/functions.md), [Валидация через promtool](./promtool_and_best_practices.md).

## Определения

*   **Правила записи (Recording Rules)** — механизм предварительного вычисления сложных или тяжелых запросов. Результат сохраняется как новый набор временных рядов (виртуальные метрики), что ускоряет работу дашбордов и алертов, а также снижает нагрузку на CPU/RAM при повторных вызовах.
*   **Правила оповещений (Alerting Rules)** — логические условия, определяющие состояние сбоя. Если выражение истинно в течение заданного времени, генерируется алерт, который затем отправляется в [Alertmanager](./alertmanager.md).
*   **Группа правил (Rule Group)** — логическое объединение правил, которые выполняются последовательно внутри группы с единым интервалом вычисления.
*   **Дребезг алертов (Flapping)** — ситуация, когда алерт быстро переключается между состояниями `Firing` и `Resolved` из-за кратковременных колебаний метрики вокруг порогового значения.
*   **Оценка (Evaluation)** — однократный проход вычисления всех правил внутри группы. По завершении评估 Prometheus обновляет внутреннее состояние алертов и записывает результаты recording rules в TSDB.

## Основные концепции

### Жизненный цикл вычисления правил

Каждый цикл оценки состоит из следующих этапов:

1.  **Забор данных (Scrape)**: Prometheus получает новые семплы от экспортеров.
2.  **Оценка групп (Evaluation)**: Для каждой группы правил вычисляется `expr` в порядке, определяемом `interval`. Если `interval` не задан явно, используется `evaluation_interval` из `prometheus.yml`.
3.  **Запись результатов**: Для recording rules результат записывается как новая временная серия. Для alerting rules обновляется внутреннее состояние (`Pending` → `Firing` или `Resolved`).
4.  **Доставка алертов**: Активные алерты отправляются в Alertmanager.

**Важно:** Оценка происходит **после** сбора данных, но **до** того, как эти данные становятся доступны для запросов через API. Это означает, что `expr` в правилах работает с данными, которые уже были собраны, но еще не попали в голову (head) TSDB для обычных запросов.

### Структура и параметры групп

Правила объединяются в группы в YAML-файлах. Группы позволяют изолировать выполнение правил, настраивать лимиты и управлять частотой вычислений.

*   **Интервал вычисления (`interval`)**: Частота выполнения правил в группе. По умолчанию наследуется из `evaluation_interval` в `prometheus.yml`. Рекомендуется устанавливать такой же или кратный интервалу сбора данных (`scrape_interval`). Если `interval` меньше `scrape_interval`, Prometheus будет пропускать циклы, так как новых данных еще нет.
*   **Смещение запроса (`query_offset`)**: (v2.53+) Задержка вычисления правила. Полезно в сценариях с [Remote Write](./scaling/remote_read_write.md) или медленной доставкой данных, чтобы гарантировать полноту данных на момент расчета. Например, если данные приходят с задержкой 2 минуты, установите `query_offset: 2m`.
*   **Лимиты кардинальности**:
    *   `limit`: Максимальное количество временных рядов, которые могут быть созданы правилами записи в этой группе. Если лимит превышен, все правила записи в группе падают с ошибкой. Нужно для защиты от взрывного роста кардинальности из-за опечаток в селекторах.
    *   `alert_limit`: Максимальное количество активных алертов, которые может сгенерировать группа. Если лимит превышен, новые алерты создаваться не будут (логируется ошибка).
*   **Последовательность и параллелизм**:
    *   Внутри одной группы правила выполняются **строго последовательно**. Это позволяет использовать результат предыдущего `record` в следующем правиле той же группы.
    *   Разные группы правил выполняются **параллельно** (независимо друг от друга). Это означает, что нельзя полагаться на порядок выполнения между группами.

### Гонка данных (Race Conditions) между Recording и Alerting Rules

Поскольку alerting rules вычисляются после recording rules в той же группе, можно безопасно использовать виртуальные метрики, созданные recording rules, в выражениях алертов той же группы. Однако между разными группами такой гарантии нет — если группа A создает метрику, а группа B на нее опирается, возможна гонка, если интервалы групп не синхронизированы.

**Рекомендация:** Размещайте recording rules и зависящие от них alerting rules в **одной группе** или синхронизируйте интервалы.

### Параметры Alerting Rules

| Параметр | Описание | Примечание |
| :--- | :--- | :--- |
| **`alert`** | Имя алерта | Должно быть уникальным, лаконичным и отражать суть проблемы. |
| **`expr`** | PromQL-выражение | Условие срабатывания. Если результат не пуст — условие выполнено. |
| **`for`** | Время ожидания | Минимальная длительность сохранения условия `true` перед переходом в `Firing`. Помогает избежать ложных срабатываний на пиках. |
| **`keep_firing_for`** | Удержание состояния | (v2.42+) Время, в течение которого алерт остается в `Firing`, даже если условие стало `false`. Предотвращает спам при дребезге. |
| **`labels`** | Дополнительные метки | Используются для маршрутизации в Alertmanager (например, `severity: critical`, `team: devops`). |
| **`annotations`** | Метаданные | Описание проблемы, шаблонизированные строки, ссылки на документацию (runbooks) и дашборды. |

**Взаимодействие `for` и `keep_firing_for`:**

*   `for: 5m` — алерт переходит в `Firing` только если условие истинно **непрерывно** 5 минут.
*   `keep_firing_for: 10m` — после того как условие стало ложным, алерт **продолжает гореть** еще 10 минут.
*   Комбинация `for: 5m` + `keep_firing_for: 10m` означает: алерт горит минимум 5+10=15 минут с момента первого срабатывания, даже если метрика нормализовалась.

### Шаблонизация в аннотациях (Templating)

Аннотации поддерживают стандартные шаблоны Go. Наиболее полезные переменные:
*   `{{ $labels.<name> }}` — значение метки из результата запроса.
*   `{{ $value }}` — численное значение выражения на момент срабатывания.
*   `{{ $externalLabels.<name> }}` — значения глобальных меток Prometheus.

*Пример:*
```yaml
annotations:
  summary: "Высокая нагрузка на CPU: {{ $labels.instance }}"
  description: "Текущее значение: {{ $value | printf \"%.2f\" }}% (порог 90%)"
```

### Состояния алертов

1.  **Inactive**: Условие не выполняется.
2.  **Pending**: Условие истинно, но время `for` еще не истекло.
3.  **Firing**: Время `for` истекло, алерт активен и отправлен в Alertmanager.
4.  **Resolved**: Условие перестало выполняться (после учета `keep_firing_for`).

## Управление и тестирование

### Валидация и применение

Для проверки синтаксиса используется утилита `promtool`.

```bash
# Проверка синтаксиса правил
promtool check rules rules.yml
# → SUCCESS: number of rules found

# Применение изменений (Hot Reload)
curl -X POST http://localhost:9090/-/reload
```

### Модульное тестирование (Unit Testing)

Prometheus позволяет тестировать логику правил без запуска сервера. Для этого создается тестовый файл (обычно `test.yml`), где описываются входные данные и ожидаемые результаты.

```yaml
# test.yml
rule_files:
  - rules.yml

evaluation_interval: 1m

tests:
  - interval: 1m
    input_series:
      - series: 'up{job="node"}'
        values: '0 0 0' # Экспортер упал на 3 минуты
    alert_rule_test:
      - eval_time: 3m
        alertname: InstanceDown
        exp_alerts:
          - labels:
              severity: critical
              instance: localhost:9100
            annotations:
              summary: "Instance down"
```

Запуск теста:
```bash
promtool test rules test.yml
# → Unit Testing: rules.yml  PASS
```

### GitOps и CI/CD

В промышленных средах правила хранятся в Git и доставляются через CI/CD. Стандартная структура репозитория:

```
monitoring-rules/
├── alerting/
│   ├── slo_rules.yml
│   ├── infrastructure_rules.yml
│   └── application_rules.yml
├── recording/
│   ├── slo_recording.yml
│   └── infrastructure_recording.yml
└── tests/
    ├── slo_tests.yml
    └── infrastructure_tests.yml
```

**Валидация в CI/CD:**
```bash
# Проверка синтаксиса всех файлов
promtool check rules monitoring-rules/**/*.yml

# Запуск тестов
promtool test rules monitoring-rules/tests/*.yml
```

**Требования к Pull Request:**
*   Указывайте, какой алерт или recording rule меняется и почему.
*   Приложите вывод `promtool test rules` к PR.
*   После мержа проверьте метрику `prometheus_rule_group_last_duration_seconds`, чтобы убедиться, что правила загрузились без ошибок.

### Самомониторинг и отладка (Self-monitoring)

Для контроля здоровья самих правил Prometheus предоставляет внутренние метрики:
*   `prometheus_rule_group_last_duration_seconds` — время последнего вычисления группы (если оно больше `interval`, сервер не справляется).
*   `prometheus_rule_evaluation_failures_total` — общее количество ошибок при вычислении правил (синтаксис, отсутствие данных, таймауты).
*   `prometheus_rule_group_iterations_missed_total` — количество пропущенных циклов вычисления из-за перегрузки.

*Совет: Всегда настраивайте алерт на `prometheus_rule_evaluation_failures_total > 0`, чтобы вовремя узнавать о сломанных правилах.*

## Практические сценарии

### Сценарий 1: Базовые правила записи для node_exporter

Предварительное вычисление часто используемых метрик снижает нагрузку на Prometheus при построении дашбордов.

```yaml
groups:
  - name: node.recording
    interval: 30s
    rules:
      # Утилизация CPU в процентах
      - record: node:cpu_utilization:ratio
        expr: |
          100 - (avg by (instance) (rate(node_cpu_seconds_total{mode="idle"}[5m])) * 100)

      # Доступная память в процентах
      - record: node:memory_utilization:ratio
        expr: |
          1 - (node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes)

      # Сеть: байты в секунду
      - record: node:network_receive_bytes:rate5m
        expr: sum by (instance) (rate(node_network_receive_bytes_total[5m]))

      # Файловая система: процент использования
      - record: node:filesystem_usage:ratio
        expr: |
          1 - (node_filesystem_free_bytes{fstype=~"ext4|xfs"} / node_filesystem_size_bytes{fstype=~"ext4|xfs"})
```

### Сценарий 2: Правила записи для SLO (Burn Rate)

Burn Rate показывает, во сколько раз текущая скорость ошибок превышает допустимую для достижения цели SLO. Использование recording rules позволяет строить стабильные алерты на основе нескольких окон.

```yaml
groups:
  - name: slo.recording
    interval: 30s
    rules:
      # Доля ошибок за 5 минут
      - record: job:http_requests:error_rate5m
        expr: |
          sum(rate(http_requests_total{status=~"5.."}[5m])) by (job)
          /
          sum(rate(http_requests_total[5m])) by (job)

      # Burn Rate = (фактическая частота ошибок) / (целевая частота ошибок)
      # Для SLO 99.9%: целевая частота ошибок = 0.1% = 0.001
      - record: job:slo:error_burn_rate
        expr: |
          job:http_requests:error_rate5m / 0.001

      # 1-часовой Burn Rate (медленные утечки бюджета)
      - record: job:slo:error_burn_rate_1h
        expr: |
          sum(rate(http_requests_total{status=~"5.."}[1h])) by (job)
          /
          sum(rate(http_requests_total[1h])) by (job)
          / 0.001
```

### Сценарий 3: Агрегация для федерации (Multi-cluster aggregation)

В крупных средах с [Thanos](./scaling/thanos_overview.md) или [Mimir](../Mimir/mimir_overview.md) правила записи используются для создания глобальных метрик с учетом `external_labels`.

```yaml
groups:
  - name: global-aggregation
    rules:
      - record: cluster:node_cpu:sum
        expr: sum by (cluster) (node_cpu_seconds_total{mode!="idle"})
```

*Здесь `cluster` — это метка, добавляемая сервером автоматически. Recording Rule позволяет быстро строить графики по всем кластерам без выкачивания всех сырых данных.*

### Сценарий 4: Стабилизация алертов с keep_firing_for

`keep_firing_for` предотвращает преждевременное закрытие инцидента при кратковременных просадках метрики.

```yaml
groups:
  - name: api.alerts
    rules:
      - alert: HighErrorRate
        expr: |
          sum by (instance) (rate(http_requests_total{status=~"5.."}[5m]))
          /
          sum by (instance) (rate(http_requests_total[5m])) > 0.05
        for: 5m
        keep_firing_for: 10m
        labels:
          severity: critical
        annotations:
          summary: "Высокая доля ошибок на {{ $labels.instance }}"
          description: "Burn Rate: {{ $value | humanize }}x. Требуется проверка логов."
```

**Поведение:**
*   Алерт переходит в `Firing` через 5 минут непрерывного превышения порога.
*   После исправления ошибок алерт остается в `Firing` еще 10 минут.
*   Это предотвращает каскад «resolve → fire», если метрика нормализовалась на 1-2 минуты из-за сезонного спада трафика.

### Сценарий 5: Алерты на отсутствие данных (NoData)

Критически важно детектировать полное отсутствие метрик от важных сервисов.

```yaml
groups:
  - name: availability.alerts
    rules:
      - alert: ServiceDown
        # up == 0 ИЛИ полное отсутствие метрики за 5 минут
        expr: up{job="my-service"} == 0 or absent_over_time(up{job="my-service"}[5m])
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "Сервис {{ $labels.job }} недоступен"
          description: "Инстанс {{ $labels.instance }} не отдает метрики более 2 минут."

      - alert: StaleMetrics
        # Метрика существует, но не обновлялась более 30 минут
        expr: time() - metric_last_update_timestamp_seconds > 30 * 60
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Устаревшие данные от {{ $labels.job }}"
```

**Рекомендация:** Для `absent()` алертов устанавливайте `for` не менее 5-10 минут, чтобы избежать ложных срабатываний при кратковременных сбоях сети.

### Сценарий 6: Динамические пороги через recording rules

Вместо жестких констант используйте recording rules для вычисления порогов на основе исторических данных.

```yaml
groups:
  - name: dynamic.thresholds
    interval: 1h
    rules:
      # Средняя задержка за неделю (rolling baseline)
      - record: job:api:p95_latency_baseline_7d
        expr: |
          quantile_over_time(0.95, http_request_duration_seconds_bucket{job="api"}[7d])

      # Алерт: текущая p95 превышает baseline более чем на 50%
      - alert: LatencyRegression
        expr: |
          histogram_quantile(0.95, rate(http_request_duration_seconds_bucket{job="api"}[5m]))
          > 1.5 * job:api:p95_latency_baseline_7d
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "Задержка API выросла относительно недельного baseline"
          runbook_url: "https://docs.internal/runbooks/latency-regression"
```

### Сценарий 7: Многооконный алертинг по скорости выгорания (Burn Rate)

Для контроля SLO используйте несколько окон, чтобы детектировать как резкие всплески, так и медленные утечки.

| Тип алерта | Окно (длинное) | Окно (короткое) | Burn Rate | Описание |
| :--- | :--- | :--- | :--- | :--- |
| **Critical** | 1 час | 5 минут | 14.4 | 2% бюджета сгорит за 1 час. |
| **Critical** | 6 часов | 30 минут | 6 | 5% бюджета сгорит за 6 часов. |
| **Warning** | 1 день | 2 часа | 3 | 10% бюджета сгорит за 24 часа. |
| **Ticket** | 3 дня | -- | 1 | Бюджет сгорает со скоростью нормы. |

**Математика:** Burn Rate = (фактическая частота ошибок) / (целевая частота). Для SLO 99.9%: целевая частота = 0.1% = 0.001. Burn Rate 14.4x означает, что ошибки происходят в 14.4 раза чаще допустимого.

```yaml
groups:
  - name: slo.multiwindow
    rules:
      - alert: SLOErrorBudgetCritical
        expr: |
          (
            job:slo:error_burn_rate_1h > 14.4
          )
          and
          (
            job:slo:error_burn_rate_5m > 14.4
          )
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "SLO: критическое выгорание бюджета ошибок ({{ $labels.job }})"
          runbook_url: "https://docs.internal/runbooks/slo-burn-rate"
          description: "Burn Rate {{ $value | humanize }}x превышает допустимый порог."
```

## Диагностика и решение проблем

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Правила не загружаются** | Синтаксическая ошибка в YAML или PromQL. | `promtool check rules`, проверка логов Prometheus (`prometheus_rule_evaluation_failures_total`). |
| **Дребезг (Flapping)** | Метрика колеблется около порога. | Увеличить `for`, использовать `keep_firing_for`, сглаживать запрос (`avg_over_time`). |
| **Alert Storm** | Отсутствие группировки в Alertmanager. | Настроить `group_by` по `alertname` и `service`. |
| **Высокая кардинальность** | Recording rule создает слишком много серий. | Установить `limit` в группе, проверить селектор на уникальные лейблы. |
| **Пропущенные инциденты** | Слишком длинный `for` или жесткие Inhibition rules. | Уменьшить окно `for`, проверить иерархию подавления. |
| **Ложные срабатывания на NoData** | Кратковременная недоступность источника. | Увеличить `for` для `absent()` алертов до 5-10 минут. |
| **Зависание оценки** | `prometheus_rule_group_last_duration_seconds` > `interval`. | Упростить выражение, добавить индексы, увеличить `interval`. |
| **Дублирование алертов** | Два Prometheus в HA-паре отправляют одни и те же алерты. | Дедупликация в Alertmanager (по умолчанию), проверка `--cluster.peer`. |
| **Устаревшие Runbooks** | Ссылки ведут на 404 или неактуальные регламенты. | Автоматизировать проверку ссылок в CI пайплайне правил. |

## Граничные случаи и ограничения

### Поведение при превышении лимитов

*   **`limit` (recording)**: Если результат выражения превышает лимит, **все** правила записи в группе падают с ошибкой. Это защищает Prometheus от OOM, но может привести к каскадному отказу алертов, зависящих от этих метрик.
*   **`alert_limit`**: Если превышен, новые алерты создаваться не будут. Логируется ошибка: `rule_group_total_alerts_exceeded`. Существующие алерты continue работать, но новые не добавляются.

### Пустые результаты и отсутствие данных

*   **Recording rule с пустым результатом**: Если выражение не возвращает данных (например, нет целей, соответствующих селектору), запись не создается. Это нормально, но может сломать downstream алерты, ожидающие наличие метрики. Используйте `unless absent(...)` или дефолтные значения.
*   **Alerting rule с пустым результатом**: Алерт не срабатывает. Это стандартное поведение PromQL — пустой результат означает «условие не выполнено».

### Взаимодействие с Alertmanager

*   **Дeduplication**: В HA-парах Prometheus автоматически дедуплицируют алерты по набору лейблов. Не добавляйте уникальные лейблы (например, `pod`, `instance`) в `group_by` в Alertmanager, если это не требуется для контекста.
*   **Inhibition**: Убедитесь, что правила подавления (inhibit_rules) не блокируют важные алерты из-за слишком широких селекторов. Тестируйте inhibition через `amtool`.

### Производительность

*   **Сложные `rate()` с большими окнами**: Избегайте `rate(metric[1h])` в алертах, если достаточно `rate(metric[5m])`. Большие окна увеличивают время вычисления и потребление памяти.
*   **Вложенные aggregation**: `sum(sum by (...))` может быть заменено на `sum by (...)` для снижения нагрузки.
*   **Native Histograms**: В Prometheus 3.0+ использование нативных гистограмм снижает кардинальность на порядки за счет удаления лейбла `le`. Переход на native histograms требует обновления экспортеров и дашбордов.

## Дополнительная информация

### Рекомендации по именованию (Best Practices)

1.  **Формат для Recording Rules**: `level:metric:operations`
    *   `instance:node_network_receive_bytes:rate5m`
    *   `job:http_requests:total` (если это сумма по всем инстансам в job).
2.  **Атомарность**: Одно правило записи должно вычислять один логический показатель. Не делайте слишком сложных цепочек внутри одной группы, если это затрудняет отладку.
3.  **Consistency**: Используйте единый формат именования во всех файлах правил. Например, всегда используйте `ratio` для долей и `:rate5m` для скоростей.

### Лучшие практики для Alerting Rules

*   **Actionability**: Каждый алерт должен требовать реакции человека или системы. Если на алерт не реагируют — он бесполезен.
*   **Runbooks**: Аннотация `runbook_url` со ссылкой на инструкцию по устранению — стандарт индустрии.
*   **Использование лейблов**:
    *   `severity`: `critical` (звонок/SMS), `warning` (Slack/Ticket), `info` (только логи).
    *   `service`: для маршрутизации конкретной команде.
*   **Борьба с шумом**: Используйте `for` (минимум 2-3 интервала сбора) и `keep_firing_for` для нестабильных метрик.
*   **Symptom-based Alerting**: Алертите на симптомы (ошибки 5xx, задержки), а не на причины (высокий CPU сам по себе не всегда проблема).
*   **Alert Budget**: Не более 5-10 страниц алертов за смену на одного дежурного. Если алерт срабатывает 100 раз в день и никогда не подтверждается — удалите или пересмотрите его.

### Версионирование и тестирование

*   **Хранение в Git**: Правила должны храниться в репозитории с историей изменений.
*   **Code Review**: Любое изменение правил проходит через Pull Request с обязательным запуском `promtool test rules`.
*   **Канареечные deployments**: При изменении критических правил развертывайте их на одном сервере сначала, наблюдайте за `prometheus_rule_evaluation_failures_total`, затем масштабируйте на весь кластер.

### Связанные ресурсы

*   Для детальных примеров алертов под конкретные типы данных см. **[Алерты для типов метрик](./concepts/metric_types/alerts.md)**.
*   Интеграция с системой уведомлений описана в **[Alertmanager](./alertmanager.md)**.
*   Методы тестирования производительности правил в **[Promtool и лучшие практики](./promtool_and_best_practices.md)**.
*   Примеры конфигурации в Kubernetes (PrometheusRule CRD) см. в **[PrometheusRule — Концепты (CRD)](./kubernetes/operator/crd/prometheusrule.md)**.
*   Официальная документация: [Prometheus Rules](https://prometheus.io/docs/prometheus/latest/configuration/recording_rules/).
