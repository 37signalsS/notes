# Примеры алертов для разных типов метрик

## Определения

**Алерты в Prometheus** — это правила оповещений (alerting rules), описывающие логические условия сбоя или аномалии. Выражения правил пишутся на языке [PromQL](../promql/functions.md). 

Если результат выполнения выражения не пуст (возвращает временной ряд) в течение времени, заданного в параметре `for`, алерт переходит в состояние `Firing` и отправляется в [Alertmanager](../../alertmanager.md) для группировки, фильтрации и доставки уведомлений.

## Основные концепции

### Связь типов метрик и алертов

Методика построения условия срабатывания напрямую зависит от семантики метрики:

| Тип метрики | Подход к алертингу | Ключевые функции |
|:---|:---|:---|
| **[Counter](./counter.md)** | Анализ скорости изменения (rate) или доли ошибок за интервал. | `rate()`, `increase()` |
| **[Gauge](./gauge.md)** | Сравнение с порогом, прогноз исчерпания ресурса или "свежесть" данных. | `predict_linear()`, `delta()`, `time()` |
| **[Histogram](./histogram.md)** | Анализ перцентилей латентности или распределения данных по бакетам. | `histogram_quantile()` |
| **Нативные гистограммы** | Анализ распределения с высокой точностью без использования лейбла `le`. | `histogram_fraction()`, `histogram_count()` |
| **[Summary](./summary.md)** | Использование заранее вычисленных квантилей (серверные метрики). | Прямое сравнение лейбла `quantile`. |
| **Отсутствие данных** | Проверка наличия метрики (детектирование падения сервиса). | `absent()`, `absent_over_time()` |

### Жизненный цикл алерта

Алерт проходит через следующие состояния:

| Состояние | Описание |
|:---|:---|
| **Inactive** | Условие не выполняется. Алerts не существует. |
| **Pending** | Условие выполняется, но не истекло время `for`. Алerts существует, но еще не отправлен. |
| **Firing** | Условие выполнялось непрерывно в течение `for` и перешло в активное состояние. Отправлен в Alertmanager. |
| **Resolved** | Условие перестало выполняться (с учетом `keep_firing_for`). Алerts закрывается. |

### Recording Rules как основа для алертов

Сложные выражения в алертах снижают производительность и усложняют отладку. Для критичных алертов используйте [recording rules](../../rules.md):

- **Предварительный расчет:** Вычисляйте `rate()`, `histogram_quantile()` или error budget заранее.
- **Стабильность:** Recording rules защищают алерты от изменений в PromQL и упрощают откат.
- **Производительность:** Виртуальные метрики переиспользуются в дашбордах и правилах без повторного вычисления.

### Принципы проектирования правил

1.  **Агрегация (`by`)**: Всегда используйте `by (instance, job, ...)` в агрегирующих функциях, чтобы сохранить важные лейблы. Без этого уведомление потеряет контекст (какой именно инстанс вызвал алерт).
2.  **Длительность (`for`)**: Устанавливайте время ожидания (например, `5m`), чтобы отсечь кратковременные всплески и дребезг (flapping).
3.  **Actionability (Действенность)**: Каждый алерт должен требовать конкретного действия от инженера. Используйте аннотацию `runbook_url` для ссылок на инструкции.
4.  **Multi-Burn Rate (SRE)**: Для критических сервисов используйте несколько окон (например, 1ч и 6ч) для детекции как резких всплесков, так и медленных утечек Error Budget.
5.  **Единообразие**: Используйте стандартные уровни важности (`severity: critical/warning/info`) для настройки маршрутизации в Alertmanager.
6.  **Удержание состояния (`keep_firing_for`)**: Используйте для нестабильных метрик, чтобы предотвратить преждевременное закрытие инцидента при кратковременных просадках.
7.  **Свежесть данных**: Для критичных проверок используйте `absent_over_time()` вместе с основной метрикой, чтобы детектировать как нарушение порога, так и полное исчезновение данных.

## Практические сценарии

### Сценарий 1: Алерт на основе Counter (Error Rate)

Детектирование всплеска ошибок HTTP 5xx относительно общего потока запросов.

```yaml
- alert: HighErrorRate
  # Доля ошибок выше 5% за последние 5 минут
  expr: |
    sum by (instance, job) (rate(http_requests_total{status=~"5.."}[5m]))
    /
    sum by (instance, job) (rate(http_requests_total[5m])) > 0.05
  for: 5m
  labels:
    severity: critical
  annotations:
    summary: "Высокая доля ошибок на {{ $labels.instance }}"
    description: "Текущая доля ошибок: {{ $value | humanizePercentage }}. Проверьте логи сервиса {{ $labels.job }}."
```

### Сценарий 2: Алерт на основе Gauge (Прогноз и Пороги)

Прогноз нехватки места на диске и критический порог загрузки CPU.

```yaml
- alert: DiskWillFill
  # Свободное место закончится в течение 4 часов (на основе тренда за час)
  expr: predict_linear(node_filesystem_free_bytes{mountpoint="/"}[1h], 4 * 3600) < 0
  for: 15m
  labels:
    severity: warning
  annotations:
    summary: "Диск переполнится в ближайшие 4 часа"
    description: "На сервере {{ $labels.instance }} раздел {{ $labels.mountpoint }} быстро заполняется."

- alert: HighCpuUsage
  # Загрузка CPU выше 90% в течение 10 минут
  expr: 100 - (avg by (instance) (rate(node_cpu_seconds_total{mode="idle"}[5m])) * 100) > 90
  for: 10m
  labels:
    severity: warning
```

### Сценарий 3: Алерт на основе Histogram (Latency)

95-й перцентиль времени ответа превышает 1 секунду.

```yaml
- alert: HighLatency
  expr: |
    histogram_quantile(0.95,
      sum by (le, instance, job) (rate(http_request_duration_seconds_bucket[5m]))
    ) > 1
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "Высокая задержка ответов API"
    description: "95-й перцентиль латентности на {{ $labels.instance }}: {{ $value | humanizeDuration }}"
```

### Сценарий 4: Алерт на основе Summary (Квантили)

Прямое использование квантилей, вычисленных приложением.

```yaml
- alert: SummaryHighLatency
  # Если 99-й квантиль, отдаваемый приложением, выше 2 секунд
  expr: http_request_duration_seconds{quantile="0.99"} > 2
  for: 10m
  labels:
    severity: warning
```

### Сценарий 5: Алерт на отсутствие данных (Service Down)

Проверка доступности таргета через внутреннюю метрику `up` или `absent`.

```yaml
- alert: ServiceDown
  # Метрика 'up' со значением 0 или полное отсутствие метрики в течение 5 минут
  expr: up == 0 or absent_over_time(up{job="my-service"}[5m])
  for: 2m
  labels:
    severity: critical
  annotations:
    summary: "Сервис {{ $labels.job }} недоступен"
    description: "Инстанс {{ $labels.instance }} перестал отдавать метрики более 2 минут назад."
```

### Сценарий 6: Алерт на Native Histograms (v3.0+)

Использование `histogram_fraction` для определения доли запросов, попадающих в заданный диапазон.

```yaml
- alert: SlowRequestsPercentageHigh
  # Процент запросов дольше 0.5с превышает 10%
  expr: |
    1 - (
      sum by (instance) (histogram_fraction(0, 0.5, http_request_duration_seconds))
    ) > 0.1
  for: 5m
  labels:
    severity: warning
```

### Сценарий 7: Информационные алерты (Info-metrics)

Детектирование несоответствия версий в кластере или изменений конфигурации.

```yaml
- alert: VersionMismatch
  # В одном job запущены разные версии ПО
  expr: count by (job) (count by (job, version) (app_info)) > 1
  for: 30m
  labels:
    severity: info
  annotations:
    summary: "Разные версии ПО в рамках одного сервиса"
    description: "В job {{ $labels.job }} обнаружено несколько версий приложения. Проверьте процесс деплоя."
```

### Сценарий 8: Алерт на "свежесть" данных (Staleness)

Мониторинг времени выполнения последнего успешного бэкапа.

```yaml
- alert: BackupFailed
  # С момента последнего успешного бэкапа прошло более 25 часов
  expr: time() - backup_last_success_timestamp_seconds > 25 * 3600
  for: 1h
  labels:
    severity: critical
  annotations:
    summary: "Бэкап не выполнялся более суток"
    description: "На сервере {{ $labels.instance }} последний успешный бэкап зафиксирован {{ $value | humanizeDuration }} назад."
```

### Сценарий 9: Multi-Burn Rate алерты (SRE)

Для контроля SLO используйте несколько окон, чтобы детектировать как резкие всплески, так и медленные утечки Error Budget. Подробные примеры и расчеты см. в [Правилах Prometheus: Multi-Burn Rate](../../rules.md#сценарий-7-многооконный-алертинг-по-скорости-выгорания-burn-rate).

```yaml
groups:
- name: slo_alerts
  rules:
  - alert: SLOErrorBudgetCritical
    # Быстрое выгорание: 14.4x за 1 час
    expr: job:slo_errors:rate_1h > 14.4
    for: 2m
    labels:
      severity: critical
    annotations:
      summary: "Критическое выгорание Error Budget (1ч окно)"

  - alert: SLOErrorBudgetWarning
    # Медленное выгорание: 3x за 6 часов
    expr: job:slo_errors:rate_6h > 3
    for: 5m
    labels:
      severity: warning
    annotations:
      summary: "Предупреждение по Error Budget (6ч окно)"
```

### Сценарий 10: Node Exporter — комплексный мониторинг инфраструктуры

Типичные алерты для bare-metal/VM серверов через [Node Exporter](../../Exporters/node_exporter.md).

```yaml
groups:
- name: node_infrastructure
  rules:
  - alert: NodeOutOfMemory
    expr: node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes * 100 < 10
    for: 5m
    labels:
      severity: warning
    annotations:
      summary: "Мало свободной памяти на {{ $labels.instance }}"
      description: "Доступно {{ $value | printf \"%.1f\" }}% RAM."

  - alert: NodeDiskAlmostFull
    expr: predict_linear(node_filesystem_free_bytes{mountpoint="/", fstype!~"tmpfs|fuse.lxcfs|squashfs"}[1h], 4*3600) < 0
    for: 15m
    labels:
      severity: warning
    annotations:
      summary: "Диск {{ $labels.mountpoint }} заполнится"

  - alert: NodeNetworkInterfaceDown
    expr: up{job="node-exporter"} == 0 or absent_over_time(up{job="node-exporter"}[5m])
    for: 2m
    labels:
      severity: critical
    annotations:
      summary: "Node exporter недоступен"
```

### Сценарий 11: Systemd Service Alerts

Мониторинг состояния системных сервисов через [Node Exporter](../../Exporters/node_exporter.md).

```yaml
- alert: SystemdServiceFailed
  expr: node_systemd_unit_state{state="failed"} == 1
  for: 1m
  labels:
    severity: critical
  annotations:
    summary: "Сервис {{ $labels.name }} в состоянии failed"
    description: "Unit {{ $labels.name }} на {{ $labels.instance }} требует внимания."

- alert: SystemdServiceRestarting
  expr: increase(node_systemd_unit_state{state="activating"}[5m]) > 3
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "Сервис {{ $labels.name }} постоянно перезапускается"
```

### Сценарий 12: Сетевая инфраструктура

Алерты на основе метрик сети от Node Exporter.

```yaml
- alert: NetworkInterfaceErrors
  expr: rate(node_network_receive_drop_total[5m]) + rate(node_network_transmit_drop_total[5m]) > 0
  for: 10m
  labels:
    severity: warning
  annotations:
    summary: "Дропы пакетов на {{ $labels.device }}"
    description: "Интерфейс {{ $labels.device }} на {{ $labels.instance }} теряет пакеты."

- alert: HighNetworkUtilization
  expr: |
    (
      rate(node_network_receive_bytes_total{device!="lo"}[5m])
      +
      rate(node_network_transmit_bytes_total{device!="lo"}[5m])
    ) / 1024 / 1024 > 100
  for: 10m
  labels:
    severity: info
  annotations:
    summary: "Высокая утилизация сети на {{ $labels.device }}"
```

### Сценарий 13: Файловая система и inode

Детектирование проблем не только с местом, но и с inode.

```yaml
- alert: FilesystemInodesLow
  expr: node_filesystem_files_free{mountpoint="/"} / node_filesystem_files_total{mountpoint="/"} * 100 < 20
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "Мало inodes на {{ $labels.mountpoint }}"

- alert: FilesystemReadOnly
  expr: node_filesystem_readonly{mountpoint="/"} == 1
  for: 1m
  labels:
    severity: critical
  annotations:
    summary: "Файловая система {{ $labels.mountpoint }} только для чтения"
```

### Сценарий 14: Тестирование алертов и CI/CD

Автоматическая проверка правил в пайплайне. Подробнее о модульном тестировании см. [Promtool и лучшие практики](../../promtool_and_best_practices.md).

```bash
# 1. Локальная проверка синтаксиса
promtool check rules /etc/prometheus/rules/*.yml
# → SUCCESS: 14 rules found

# 2. Модульное тестирование с синтетическими данными
promtool test rules /etc/prometheus/tests/alerting_tests.yml

# 3. Проверка загрузки правил через API
curl -s http://localhost:9090/api/v1/rules | jq '.data.groups[] | .name'
```

```yaml
# test.yml — пример модульного теста для алерта
rule_files:
  - rules.yml

evaluation_interval: 1m

tests:
  - interval: 1m
    input_series:
      - series: 'http_requests_total{status="500"}'
        values: '0+1x10'
      - series: 'http_requests_total'
        values: '10+1x10'
    alert_rule_test:
      - alertname: HighErrorRate
        eval_time: 10m
        exp_alerts:
          - active: true
            labels:
              severity: critical
```

## Дополнительная информация

### Шаблонизация аннотаций

Prometheus использует Go-templates для динамического формирования текста уведомлений. 

**Основные функции:**
- `{{ $labels.<name> }}`: Значение метки (например, `{{ $labels.instance }}`).
- `{{ $value | humanize }}`: Округление и добавление префиксов (K, M, G).
- `{{ $value | humanizeDuration }}`: Преобразование секунд в формат `1h 5m`.
- `{{ $value | humanizePercentage }}`: Преобразование `0.057` в `5.7%`.
- `{{ $value | printf "%.2f" }}`: Форматирование числа с плавающей точкой.
- `{{ query "expression" }}`: Выполнение дополнительного запроса (использовать с осторожностью для избежания нагрузки).

### Отладка и тестирование

1.  **Expression Browser**: Проверка `expr` в UI Prometheus перед фиксацией правила.
2.  **`promtool check rules`**: Валидация синтаксиса YAML и PromQL-выражений.
3.  **Unit Testing**: Создание тестовых сценариев с синтетическими данными для проверки логики срабатывания. Подробнее см. в разделе **[Валидация через promtool](../../promtool_and_best_practices.md)**.
4.  **ALERTS метрика**: Prometheus создает внутреннюю метрику `ALERTS`, которую можно использовать для мониторинга активности самих алертов.
5.  **Проверка загрузки правил**: После деплоя проверьте, что Prometheus загрузил правила:
    ```bash
    curl -s http://localhost:9090/api/v1/rules | jq '.data.groups[] | {name: .name, rules: (.rules | length)}'
    ```

### Устранение неполадок

| Симптом | Причина | Решение |
|:---|:---|:---|
| Алерт срабатывает, но Alertmanager не отправляет уведомление | Неправильная маршрутизация или `group_by` | Проверьте конфигурацию Alertmanager и логи доставки. |
| Частые срабатывания (flapping) | Слишком короткий `for` или нестабильная метрика | Увеличьте `for`, используйте `avg_over_time`, добавьте `keep_firing_for`. |
| Алерт не срабатывает при падении сервиса | Используется только `up`, но метрика устарела | Добавьте `absent_over_time(up[5m])` к выражению. |
| Правило не загружается | Ошибка синтаксиса YAML или PromQL | `promtool check rules`, проверьте логи Prometheus. |
| Много одинаковых алертов | Отсутствует агрегация `by` или `group_by` | Добавьте `by (job, instance)` в выражение и настройте группировку. |
| Алерт "висит" после восстановления | `keep_firing_for` слишком большой или метрика возвращается не полностью | Уменьшите `keep_firing_for`, проверьте выражение. |

### Защита от шума (Alert Fatigue)

- **Минимальный `for`:** Не устанавливайте `for` меньше `2 * scrape_interval`. Для `scrape_interval=15s` минимум `30s`.
- **Группировка:** В Alertmanager группируйте по `alertname` + `service`, но не по `instance`.
- **Inhibition:** Настройте подавление зависимых алертов. Например, `ServiceDown` подавляет `HighLatency` для того же сервиса. Подробнее см. в [Alertmanager](../../alertmanager.md).
- **Silence:** Используйте сайленсы для плановых работ. Создавайте их через `amtool` или UI Alertmanager с указанием причины и продолжительности.
- **Severity:** Никогда не отправляйте `info` алерты в канал оповещений; используйте их только для дашбордов.

### Рекомендации по именованию алертов

1.  **Суффикс `Critical`/`Warning`/`Info`** не добавляйте в имя — используйте `labels.severity`.
2.  **Формат:** `<Component><Condition>` (например, `NodeDiskAlmostFull`, `HighErrorRate`).
3.  **Единственное число:** `DiskFull`, а не `DisksFull`.
4.  **Старая конвенция `Prometheus`/`NodeExporter`** в начале имени устарела; современный стиль — `<BusinessImpact>`.

### См. также

- [Alertmanager](../../alertmanager.md) — обработка и маршрутизация уведомлений.
- [Правила алертинга](../../rules.md) — параметры групп, `for`, `keep_firing_for`, unit-тесты и multi-burn rate.
- [Counter](./counter.md), [Gauge](./gauge.md), [Histogram](./histogram.md), [Summary](./summary.md) — детальное описание типов метрик.
- [PromQL: функции](../promql/functions.md) — справочник по языку запросов.
- [Promtool и лучшие практики](../../promtool_and_best_practices.md) — валидация и тестирование правил.
- [Поведение метрик в реальных условиях](../promql/real_world_behavior.md) — staleness, extrapolation, обработка рестартов.
