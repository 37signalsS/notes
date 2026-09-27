# Шаблоны запросов PromQL

## Определения

**Шаблоны запросов (Query Patterns)** — проверенные на практике PromQL-выражения для решения типовых задач мониторинга. Каждый шаблон комбинирует [функции](./functions.md), [операторы агрегации](./aggregation.md) и [селекторы](./selectors_operators.md) в единую логическую конструкцию.

Актуально для **Prometheus v3.0+**, включая нативную поддержку OpenTelemetry (OTLP), нативные гистограммы и новые возможности метаданных.

Для системного подхода к мониторингу рекомендуется использовать стандартные методологии:
- **RED (Rate, Errors, Duration)** — для анализа состояния сервисов и приложений.
- **USE (Utilization, Saturation, Errors)** — для анализа состояния ресурсов и инфраструктуры.
- **Four Golden Signals** (Latency, Traffic, Errors, Saturation) — фундамент мониторинга SRE.

## Базовые концепции

### Принцип построения запроса

Каждый запрос строится по схеме: выбор метрики → фильтрация по лейблам → сдвиг во времени (`offset`) → вычисление скорости/прироста (`rate`/`increase`) → агрегация (`sum by`, `avg by`) → арифметические операции (проценты, отношения).

**Почему важен порядок операций:** Prometheus вычисляет запрос сверху вниз. Неправильный порядок (например, `sum()` до `rate()`) приводит к потере информации о сбросах счётчиков и искажению данных. Подробнее о механизме обработки сбросов см. [Реальное поведение метрик](./real_world_behavior.md).

### Расчёт долей и процентов

Общая формула отношения событий:
```promql
# Доля успешных запросов (SLA/SLI)
sum(rate(http_requests_total{status=~"2.."}[5m]))
/
sum(rate(http_requests_total[5m]))
```
Результат — значение от 0 до 1. Для получения процентов умножьте на `100`.

**Математическое обоснование:** При делении двух векторов Prometheus выполняет сопоставление лейблов. Если в числителе и знаменателе наборы лейблов совпадают, результат сохранит эти лейблы. Если совпадение частичное, используйте модификаторы `on`/`ignoring` для явного указания ключей сопоставления.

### Перцентили и квантили

Вычисляются исключительно через `histogram_quantile` над агрегированными корзинами:
```promql
# Обязательная агрегация sum(rate(...)) by (le)
histogram_quantile(0.99, sum by (le) (rate(http_request_duration_seconds_bucket[5m])))
```
Подробнее об устройстве — [Гистограммы](../metric_types/histogram.md).

**Важно:** Для классических гистограмм лейбл `le` (less or equal) должен присутствовать в списке группировки `by`. Без него функция не сможет построить распределение. Нативные гистограммы (v3.0) не требуют лейбла `le` и работают напрямую.

### Окна и интервалы агрегации

Интервал (например, `[5m]`) должен быть связан с частотой сбора метрик (`scrape_interval`).

**Правило 4 точек:** Для корректного вычисления `rate()` в окне должно гарантированно находиться минимум 4 точки scrape. При `scrape_interval = 15s` минимальный безопасный интервал = `1m`. При `30s` = `2m`.

В Grafana традиционно использовалась переменная `$__interval` (зависящая от масштаба (zoom) графика). Это приводило к катастрофе: при сильном приближении окна `$__interval` мог стать меньше `scrape_interval`, и графики исчезали.

**Решение:** Всегда использовать **`$__rate_interval`** в Grafana. Эта переменная гарантирует: `max($__interval, 4 * scrape_interval)`.

## Практические сценарии

### Методология RED (Мониторинг сервисов)

**Rate (Интенсивность трафика):**
```promql
# Суммарный RPS всех инстансов сервиса
sum(rate(http_requests_total[5m])) by (service)
# → {service="auth"} 150.5
```

**Errors (Ошибки):**
```promql
# Интенсивность ошибок 5xx по путям (path)
sum(rate(http_requests_total{code=~"5.."}[5m])) by (path)
# → {path="/api/login"} 2.1
```

**Duration (Длительность/Латентность):**
```promql
# 95-й перцентиль времени ответа по методам (Classic Histograms)
histogram_quantile(0.95, 
  sum by (le, method) (rate(http_request_duration_seconds_bucket[5m]))
)
# → {method="GET"} 0.12

# 95-й перцентиль через Native Histograms (v3.0) — точнее и эффективнее
histogram_quantile(0.95, sum by (method) (rate(http_request_duration_seconds[5m])))
# → {method="GET"} 0.115
```

### Методология USE (Инфраструктура)

**Utilization (Утилизация ресурсов):**
```promql
# Утилизация CPU (инверсия idle) по узлам
100 - (avg by (instance) (irate(node_cpu_seconds_total{mode="idle"}[5m])) * 100)
# → {instance="node-1"} 45.5

# Использование оперативной памяти (в %)
(1 - node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes) * 100
# → {instance="node-1"} 62.1
```

**Saturation (Насыщенность/Очереди):**
```promql
# Нагрузка относительно количества ядер (Saturation)
node_load1 / count by (instance) (node_cpu_seconds_total{mode="idle"})
# → {instance="node-2"} 1.5 (перегрузка, если > 1)

# Дисковый I/O (Saturation через время операций)
rate(node_disk_io_time_seconds_total[5m])
# → {device="sda"} 0.8 (близко к пределу 1.0)
```

**Errors (Ошибки оборудования/сети):**
```promql
# Скорость ошибок на сетевом интерфейсе (Errors)
rate(node_network_receive_errs_total{device="eth0"}[5m])
# → {device="eth0"} 0.05
```

### Мониторинг ресурсов Kubernetes

**Потребление памяти контейнерами (RSS):**
```promql
# Топ-5 потребителей памяти в неймспейсе
topk(5, sum by (pod) (container_memory_rss{container!="", namespace="prod"}))
# → {pod="api-7f6d"} 512MiB
```

**CPU Throttling (Saturation):**
```promql
# Процент времени, когда CPU контейнера ограничивался (throttled)
sum by (container, pod) (rate(container_cpu_cfs_throttled_seconds_total[5m]))
/
sum by (container, pod) (rate(container_cpu_usage_seconds_total[5m])) * 100
# → {pod="worker-1"} 12.5 (значение > 10% требует внимания)
```

**Количество подов в состоянии Running:**
```promql
sum by (namespace) (kube_pod_status_phase{phase="Running"})
# → {namespace="prod"} 24
```

### SLI/SLO и Error Budget

**Burn Rate (Скорость сжигания бюджета ошибок):**
```promql
# Burn rate за последний час (для окна SLO 30 дней)
sum(rate(http_requests_total{status=~"5.."}[1h]))
/
sum(rate(http_requests_total[1h])) > 14.4
# → 14.4x burn rate означает исчерпание месячного бюджета за ~2 дня
```

**Процент доступности (Availability SLI):**
```promql
sum(rate(http_requests_total{status=~"2..|3.."}[5m]))
/
sum(rate(http_requests_total[5m])) * 100
# → 99.97% доступности
```

### Детекция изменений и инцидентов

**Resets (Рестарты контейнеров):**
```promql
# Обнаружение рестартов — больше 3 за час
resets(process_cpu_seconds_total[1h]) > 3
# → {instance="node-1"} 1
```

**Changes (Частые изменения состояния):**
```promql
# Метрика, которая меняется чаще 10 раз за час (например, переключение флага)
changes(node_uname_info[1h]) > 10
```

**Absent Over Time (Отсутствие данных):**
```promql
# Сервис не отправлял метрики 15 минут (absent_over_time)
absent_over_time(up{job="critical-service"}[15m])
# → 1 (если метрика отсутствует)
```

### Работа с метаданными (v3.0+)

**Обогащение через `info()` (exp):**
Автоматически добавляет лейблы из инфо-метрик без сложных `group_left`.
```promql
# Добавить версию из node_info к метрике загрузки CPU
info(node_load1, node_info)
# → {instance="node-1", version="v1.2.3"} 0.85
```

**Сортировка по лейблам через `sort_by_label()` (exp):**
```promql
# Топ-5 ошибок, отсортированных по имени сервиса для Grafana
sort_by_label(topk(5, rate(errors_total[5m])), "service")
```

### Продвинутые паттерны и обнаружение аномалий

**Z-Score (Детекция всплесков):**
Сравнивает текущий rate со средним и стандартным отклонением за период.
```promql
# Отклонение более чем на 3 сигмы
(
  rate(http_requests_total[5m]) - avg_over_time(rate(http_requests_total[5m])[1h:5m])
) 
/ 
stddev_over_time(rate(http_requests_total[5m])[1h:5m]) > 3
# → {path="/api/attack"} 4.2
```

**Прогноз исчерпания диска (Linear Prediction):**
```promql
# Место на диске закончится через 4 часа (на основе данных за 1 час)
predict_linear(node_filesystem_free_bytes{mountpoint="/"}[1h], 3600 * 4) < 0
# → {instance="db-1"} 1
```

**Медианное абсолютное отклонение (MAD) для детекции аномалий:**
```promql
# Аномалия, если текущее значение отклоняется от медианы более чем на 3 MAD
(
  rate(http_requests_total[5m])
  -
  median_over_time(rate(http_requests_total[5m])[1h:5m])
) 
>
  3 * mad_over_time(rate(http_requests_total[5m])[1h:5m])
```

### Снижение кардинальности и оптимизация

**TopK / BottomK для ограничения количества рядов:**
```promql
# Топ-5 самых нагруженных эндпоинтов
topk(5, sum by (path) (rate(http_requests_total[5m])))
```

**Count Values для инвентаризации:**
```promql
# Количество уникальных значений лейбла (например, версий приложения)
count_values("version", build_info)
# → {version="v1.2.3"} 12
```

**Group() для проверки наличия:**
```promql
# Возвращает 1 для каждого уникального набора лейблов
group by (job, instance) (up)
# → {job="node-exporter", instance="node-1"} 1
```

## Методология SLI/SLO и Error Budget

### Определения

**SLI (Service Level Indicator)** — количественная метрика, отражающая уровень качества сервиса. Вычисляется как доля успешных событий от общего числа (например, доля запросов с кодом 2xx).

**SLO (Service Level Objective)** — целевое значение SLI за определённый период (например, 99.9% доступности за 30 дней). SLO определяет, сколько ошибок команда может себе позволить.

**Error Budget** — разница между SLO и фактическим SLI. Если SLO = 99.9%, Error Budget = 0.1% (около 43 минут простоя за 30 дней). Исчерпание бюджета означает необходимость приостановки деплоев и фокуса на стабильность.

**Burn Rate** — скорость, с которой Error Budget исчерпывается. Burn Rate = 1 означает, что бюджет сгорает ровно за отведённый период. Burn Rate = 14.4 означает, что месячный бюджет сгорит за ~2 дня.

### Формулы SLI

**Availability (Доступность):**
```promql
# SLI = (успешные запросы) / (все запросы)
sum(rate(http_requests_total{status=~"2..|3.."}[5m]))
/
sum(rate(http_requests_total[5m]))
# → 0.9997 (99.97% доступности)
```

**Error Rate (Частота ошибок):**
```promql
# SLI = (ошибки сервера) / (все запросы)
sum(rate(http_requests_total{status=~"5.."}[5m]))
/
sum(rate(http_requests_total[5m]))
# → 0.0003 (0.03% ошибок)
```

**Latency (Латентность):**
```promql
# SLI = доля запросов быстрее порога
histogram_quantile(0.99, sum by (le) (rate(http_request_duration_seconds_bucket[5m])))
# → 0.15 (p99 = 150ms)
```

### Расчёт Error Budget

```promql
# Error Budget = 1 - SLO (в долях)
# Для SLO 99.9%: Error Budget = 0.001 (0.1%)

# Фактический Error Budget (сколько осталось)
# За 30 дней: 30 * 24 * 60 * 0.001 = 43.2 минуты простоя

# Текущий расход бюджета за день
sum(increase(http_requests_total{status=~"5.."}[1d]))
/
sum(increase(http_requests_total[1d]))
# → 0.0002 (за день израсходовано 0.02% из 0.1% месячного бюджета)
```

### Multi-Window Burn Rate Alerting

Для SRE-алERTing используется комбинация двух окон для фильтрации ложных срабатываний:

| Уровень | Длинное окно | Короткое окно | Burn Rate | Время до исчерпания бюджета |
|:---|:---|:---|:---|:---|
| Critical | 1 час | 5 минут | 14.4x | ~2 дня |
| Critical | 6 часов | 30 минут | 6x | ~5 дней |
| Warning | 1 день | 2 часа | 3x | ~10 дней |
| Ticket | 3 дня | -- | 1x | ~30 дней |

**Recording rules для Burn Rate:**
```yaml
groups:
  - name: slo_recording
    interval: 30s
    rules:
      # Error rate за 5 минут
      - record: job:http_requests:error_rate5m
        expr: |
          sum(rate(http_requests_total{status=~"5.."}[5m])) by (job)
          /
          sum(rate(http_requests_total[5m])) by (job)

      # Burn Rate (5-минутное окно)
      - record: job:slo:burn_rate_5m
        expr: |
          job:http_requests:error_rate5m / 0.001

      # Burn Rate (1-часовое окно)
      - record: job:slo:burn_rate_1h
        expr: |
          sum(rate(http_requests_total{status=~"5.."}[1h])) by (job)
          /
          sum(rate(http_requests_total[1h])) by (job)
          / 0.001
```

**Alerting rules для Multi-Window Burn Rate:**
```yaml
groups:
  - name: slo_alerts
    rules:
      # Critical: 14.4x burn rate за 1ч И 5м
      - alert: SLOBurnRateCritical
        expr: |
          job:slo:burn_rate_1h > 14.4
          and
          job:slo:burn_rate_5m > 14.4
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "SLO: критическое исчерпание бюджета ошибок ({{ $labels.job }})"

      # Warning: 3x burn rate за 1д И 2ч
      - alert: SLOBurnRateWarning
        expr: |
          job:slo:burn_rate_1d > 3
          and
          job:slo:burn_rate_2h > 3
        for: 15m
        labels:
          severity: warning
        annotations:
          summary: "SLO: предупреждение о скорости исчерпания бюджета ({{ $labels.job }})"
```

### Алерт на исчерпание Error Budget

```promql
# Error Budget исчерпан на 80%
1 - (
  sum(increase(http_requests_total{status=~"5.."}[30d])) by (job)
  /
  sum(increase(http_requests_total[30d])) by (job)
) < 0.2
# → {job="api"} 1 (бюджет исчерпан на 80%)
```

### Диагностика SLO

```promql
# Текущий SLI за 30 дней
avg_over_time(
  (
    sum(rate(http_requests_total{status=~"2..|3.."}[5m])) by (job)
    /
    sum(rate(http_requests_total[5m])) by (job)
  )[30d:5m]
) * 100
# → {job="api"} 99.95

# Оставшийся Error Budget в минутах
(1 - (
  sum(increase(http_requests_total{status=~"5.."}[30d])) by (job)
  /
  sum(increase(http_requests_total[30d])) by (job)
)) * 30 * 24 * 60
# → {job="api"} 21.6 (осталось 21.6 минут из 43.2)
```

## Дополнительная информация

### Типичные ошибки запросов

| Ошибка | Последствие | Решение |
|:---|:---|:---|
| `rate(sum(...))` вместо `sum(rate(...))` | Искажение данных при рестартах | Сначала вычислять `rate()` для каждого ряда, затем `sum()` |
| Окно `[1m]` для `rate()` | Высокий шум, пропуски точек | Использовать окно минимум 3-4x `scrape_interval` |
| Использование `irate()` в алертах | Флаппинг от микро-спайков | Использовать `rate()` с окном `5m`+ и `for: 3m` |
| Сравнение `== 1` для `increase()` | Алерт не сработает из-за дробной экстраполяции | Использовать `>= 1` или `> 0` |
| Забытый лейбл `le` в `histogram_quantile` | Возврат `NaN` | Добавить `le` в `sum by (...)` |
| Суммирование температур/процентов | Безрезультатное или ложное значение | Использовать `avg` вместо `sum` для неаддитивных величин |
| Агрегация `by (pod, instance)` в recording rules | Ряды исчезают при пересоздании пода | Использовать `by (deployment, namespace)` |

### Производительность запросов

| Тип операции | Стоимость | Рекомендация |
|:---|:---|:---|
| `rate()` / `irate()` | Низкая | Безопасно использовать в алертах. |
| `predict_linear()` | Средняя | Ограничьте окно 1–24 часа. |
| `histogram_quantile()` | Средняя/Высокая | Сначала агрегируйте `sum by (le)`, затем вычисляйте квантиль. |
| `..._over_time()` с большим окном | Высокая | Избегайте окон >24h для высококардинальных метрик. |
| `label_replace()` со сложным regex | Средняя | Используйте простые паттерны; тестируйте на `promtool`. |

### Предостережения

- **`irate()` vs `rate()`**: `irate()` чувствителен к мгновенным скачкам и подходит для графиков с высокой детализацией. Для алертов всегда используйте `rate()`.
- **Агрегация и Counter**: Сначала `rate()`, потом `sum()`. Выражение `rate(sum(...))` — **ошибка**, приводящая к искажению данных при рестартах.
- **OTLP Совместимость**: При работе с метриками OpenTelemetry через Prometheus v3.0, используйте паттерны нативных гистограмм для корректного отображения экспоненциальных бакетов.
- **Grafana и `$__rate_interval`**: Всегда используйте эту переменную для автоматического выбора окна агрегации в зависимости от шага графика.
- **Нативные гистограммы**: Не смешивайте обычные float-метрики и нативные гистограммы в одной группе агрегации. Ряды несовпадающих типов будут исключены из результата.

### Выбор интервала
- **Оперативный мониторинг**: 1m–5m (сглаживание шума).
- **Анализ трендов**: 30m–1h.
- **Алертинг**: 5m–15m (баланс между скоростью срабатывания и стабильностью).
- **Прогнозы**: 1h–24h (большие окна дают более стабильный тренд).

> **См. также:**
>
> - [Функции PromQL](./functions.md) — классификация и справочник функций.
> - [Типы данных](./data_types.md) — различие между мгновенными и интервальными векторами.
> - [Операции с векторами](./vector_operations.md) — сопоставление векторов (`on`, `ignoring`, `group_left`).
> - [Реальное поведение метрик](./real_world_behavior.md) — нюансы экстраполяции и staleness.
