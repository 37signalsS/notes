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

### Принципы проектирования правил

1.  **Агрегация (`by`)**: Всегда используйте `by (instance, job, ...)` в агрегирующих функциях, чтобы сохранить важные лейблы. Без этого уведомление потеряет контекст (какой именно инстанс вызвал алерт).
2.  **Длительность (`for`)**: Устанавливайте время ожидания (например, `5m`), чтобы отсечь кратковременные всплески и дребезг (flapping).
3.  **Actionability (Действенность)**: Каждый алерт должен требовать конкретного действия от инженера. Используйте аннотацию `runbook_url` для ссылок на инструкции.
4.  **Multi-Burn Rate (SRE)**: Для критических сервисов используйте несколько окон (например, 1ч и 6ч) для детекции как резких всплесков, так и медленных утечек Error Budget.
5.  **Единообразие**: Используйте стандартные уровни важности (`severity: critical/warning/info`) для настройки маршрутизации в Alertmanager.

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

### См. также

- [Alertmanager](../../alertmanager.md) — обработка и маршрутизация уведомлений.
- [Rules и алертинг](../../rules.md) — общие правила настройки и состояния алертов.
- [Counter](./counter.md), [Gauge](./gauge.md), [Histogram](./histogram.md), [Summary](./summary.md) — детальное описание типов метрик.
- [PromQL: функции](../promql/functions.md) — справочник по языку запросов.

---
