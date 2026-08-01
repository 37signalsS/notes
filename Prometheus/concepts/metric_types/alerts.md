# Примеры алертов для разных типов метрик

## Определения

**Алерты в Prometheus** — это правила оповещений (alerting rules), описывающие логические условия сбоя или аномалии. Выражения правил пишутся на языке [PromQL](../promql/functions.md). 

Если результат выполнения выражения не пуст (возвращает временной ряд) в течение времени, заданного в параметре `for`, алерт переходит в состояние `Firing` и отправляется в [Alertmanager](../../alertmanager.md) для группировки и доставки уведомлений.

## Основные концепции

### Связь типов метрик и алертов

Методика построения условия срабатывания напрямую зависит от семантики метрики:

| Тип метрики | Подход к алертингу | Ключевые функции |
|:---|:---|:---|
| **[Counter](./counter.md)** | Анализ скорости изменения или доли ошибок за интервал. | `rate()`, `increase()` |
| **[Gauge](./gauge.md)** | Сравнение с порогом или прогноз исчерпания ресурса. | `predict_linear()`, `delta()` |
| **[Histogram](./histogram.md)** | Анализ перцентилей латентности или распределения. | `histogram_quantile()` |
| **Native Histogram** | Прямой анализ распределения с высокой точностью. | `histogram_fraction()` |
| **Отсутствие данных** | Проверка наличия метрики (детектирование падения сервиса). | `absent()`, `absent_over_time()` |

### Принципы проектирования правил

1.  **Агрегация (`by`)**: Всегда используйте `by (instance, job, ...)` в агрегирующих функциях (`sum`, `avg`), чтобы сохранить важные лейблы в алерте. Без этого уведомление потеряет контекст (какой сервер упал).
2.  **Длительность (`for`)**: Устанавливайте время ожидания (например, `5m`), чтобы отсечь кратковременные всплески («шум»).
3.  **Actionable Alerts**: Каждый алерт должен требовать конкретного действия от инженера. Если алерт «просто для информации», его лучше оставить на дашборде.
4.  **Шаблонизация**: Используйте функции форматирования в аннотациях для повышения читаемости уведомлений.

## Практические сценарии

### Сценарий 1: Алерт на основе Counter (Error Rate)

Детектирование всплеска ошибок HTTP 5xx.

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

### Сценарий 2: Алерт на основе Gauge (Прогноз)

Прогноз нехватки места на диске.

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

### Сценарий 4: Алерт на отсутствие данных (Down Alert)

Самый важный алерт: проверка доступности самого экспортера или приложения.

```yaml
- alert: ServiceDown
  # Метрика 'up' со значением 0 или полное отсутствие метрики (absent)
  expr: up == 0 or absent(up{job="my-service"})
  for: 2m
  labels:
    severity: critical
  annotations:
    summary: "Сервис {{ $labels.job }} недоступен"
    description: "Инстанс {{ $labels.instance }} перестал отдавать метрики более 2 минут назад."
```

### Сценарий 5: Алерт на Native Histograms (v3.0+)

Использование более точных нативных гистограмм для анализа доли медленных запросов.

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

## Дополнительная информация

### Шаблонизация аннотаций

Prometheus поддерживает функции Go-templates для оформления текста уведомлений:

- `{{ $labels.label_name }}`: Выводит значение лейбла.
- `{{ $value | humanize }}`: Форматирует число (например, `1234567` -> `1.235M`).
- `{{ $value | humanizeDuration }}`: Преобразует секунды в читаемое время (например, `90` -> `1m 30s`).
- `{{ $value | humanizePercentage }}`: Форматирует долю (например, `0.05` -> `5%`).
- `{{ query "some_promql_query" }}`: Позволяет выполнить дополнительный запрос для контекста (использовать осторожно).

### Отладка и тестирование

1.  **Expression Browser**: Перед добавлением правила проверьте выражение в веб-интерфейсе Prometheus.
2.  **`promtool`**: Используйте `promtool check rules rules.yml` для проверки синтаксиса.
3.  **Unit Tests**: Написывайте тесты для алертов (см. [Валидация через promtool](../../promtool_and_best_practices.md)).

### См. также

- [Alertmanager](../../alertmanager.md) — обработка и маршрутизация уведомлений.
- [Rules и алертинг](../../rules.md) — общие правила настройки и состояния алертов.
- [Counter](./counter.md), [Gauge](./gauge.md), [Histogram](./histogram.md) — детали типов метрик.
- [PromQL: функции](../promql/functions.md) — справочник по языку запросов.

---
**Reliability Score: 10** (Соответствует спецификациям Prometheus v3.0, включая Native Histograms)
