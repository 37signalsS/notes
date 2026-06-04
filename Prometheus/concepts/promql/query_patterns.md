# Шаблоны запросов PromQL

## Определения

**Шаблоны запросов (Query Patterns)** — повторно используемые PromQL-выражения для типовых задач мониторинга. Каждый шаблон решает конкретную задачу: расчёт утилизации, скорости событий, перцентилей или алертинга. Шаблоны комбинируют [функции PromQL](./functions.md), [операторы агрегации](./aggregation.md) и [селекторы](./selectors_operators.md) в единое выражение.

**Принцип построения:** выбор метрики → фильтрация по лейблам → обработка функцией (`rate()`, `histogram_quantile()`) → агрегация (`sum by`, `avg by`) → математическая операция (проценты, доли).

## Базовые концепции

### Утилизация ресурсов

Для расчёта утилизации используется формула `(1 - available / total) × 100`. Для CPU — средняя скорость idle-времени через `rate()` или `irate()`.

### Доли и отношения

Доля событий вычисляется как `rate(нужные_события) / rate(все_события)`. Используется для SLO/SLI — например, доля успешных HTTP-запросов.

### Перцентили

Вычисляются через `histogram_quantile(φ, sum by (le) (rate(..._bucket[interval])))`. Показывают распределение латентности, размеров запросов и других величин ([Гистограммы](../metric_types/histogram.md)).

### Алертинг по отсутствию метрики

Функция `absent()` возвращает `1`, если метрика не найдена. Используется для обнаружения упавших exporter'ов или сервисов.

## Практические сценарии

### Мониторинг инфраструктуры (Node Exporter)

**Утилизация CPU по instance (в %):**

```promql
avg by (instance) (irate(node_cpu_seconds_total{mode="idle"}[5m])) * 100
```

Использует `irate()` для мгновенной скорости idle-времени. Инверсия (`* 100`) даёт процент использования. Подробнее о метриках — [Node Exporter](../../Exporters/node_exporter.md).

**Использование памяти (в %):**

```promql
(1 - node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes) * 100
```

Gauge-метрики, не требуют `rate()`. Показывают текущее состояние.

**Использование диска (в %):**

```promql
(1 - node_filesystem_avail_bytes{mountpoint="/"} / node_filesystem_size_bytes{mountpoint="/"}) * 100
```

Рекомендуется фильтровать по `mountpoint` для избежания дублирования виртуальных ФС.

**Входящий сетевой трафик (байт/сек):**

```promql
rate(node_network_receive_bytes_total{device="eth0"}[5m])
```

Counter — обязательно `rate()`. Фильтр по `device` для конкретного интерфейса.

### Мониторинг приложений

**Доля ошибок HTTP 5xx:**

```promql
sum(rate(http_requests_total{code=~"5.."}[5m]))
/
sum(rate(http_requests_total[5m]))
```

Отношение rate'ов — ключевой SLO/SLI для доступности. Результат — доля (0.05 = 5%).

**95-й перцентиль времени ответа:**

```promql
histogram_quantile(0.95,
  sum(rate(http_request_duration_seconds_bucket[5m])) by (le)
)
```

Обязательна агрегация `sum by (le)` перед `histogram_quantile()` — иначе перцентиль посчитается для каждого инстанса отдельно ([Перцентили](../metric_types/percentiles.md)).

**RPS (запросов в секунду):**

```promql
sum(rate(http_requests_total[5m]))
```

Суммарная скорость запросов по всем инстансам — единственно корректный способ агрегации Counter ([Счётчики](../metric_types/counter.md)).

### Мониторинг Kubernetes

**Количество подов в состоянии Running:**

```promql
sum(kube_pod_status_phase{phase="Running"})
```

Метрика из kube-state-metrics. Gauge — агрегация через `sum()`. Подробнее — [Kubernetes](../../kubernetes/overview.md).

**Использование CPU контейнером (в ядрах):**

```promql
rate(container_cpu_usage_seconds_total{container!=""}[5m])
```

Counter — `rate()` даёт ядра CPU. Фильтр `container!=""` исключает мета-контейнеры. Подробнее — [cAdvisor](../../Exporters/cadvisor.md).

**Использование памяти контейнером:**

```promql
container_memory_usage_bytes{container!=""}
```

Gauge — показывает текущее потребление без обработки.

### Алертинг

**Проверка отсутствия метрики:**

```promql
absent(up{job="my-critical-service"})
```

Возвращает `1`, если сервис не скрейпится — алерт для Alertmanager ([Rules](../../rules.md)).

**Сервис недоступен:**

```promql
up{job="api-server"} == 0
```

Метрика `up` = 0 — таргет не отвечает.

**Прогноз нехватки диска через 4 часа:**

```promql
predict_linear(node_filesystem_free_bytes{mountpoint="/"}[1h], 3600 * 4) < 0
```

Линейная экстраполяция по данным за последний час. Срабатывает **до** того, как место закончится ([Измерители](../metric_types/gauge.md)).

**Высокая загрузка CPU (>80% в течение 10 минут):**

```promql
avg by (instance) (irate(node_cpu_seconds_total{mode="idle"}[5m])) * 100 < 20
```

Инверсия idle (< 20% idle = > 80% usage). Порог 10 минут снижает ложные срабатывания при кратковременных всплесках.

## Дополнительная информация

### Предостережения

- **`irate()` vs `rate()` для алертинга** — `irate()` чувствителен к шуму, для алертов предпочтительнее `rate()` с длительным окном ([Реальное поведение метрик](./real_world_behavior.md)).
- **Гистограммы без `sum by (le)`** — `histogram_quantile()` без агрегации посчитает перцентиль для каждого инстанса, что приведёт к множеству линий на графике.
- **`$__rate_interval` в Grafana** — используйте вместо `$__interval` для корректного расчёта rate, минимум 4×scrape_interval.
- **Counter vs Gauge** — не применяйте `rate()` к Gauge и `deriv()` к Counter. Counter только растёт, Gauge — произвольно меняется ([Типы метрик](../metric_types/overview.md)).

### Выбор интервала

- **Ручные запросы:** 5m для сглаженных графиков, 1–2m для детального анализа.
- **Grafana:** переменная `$__rate_interval`, минимум 1m (2×scrape_interval).
- **Алертинг:** 5–15m для снижения шума, с `for` для задержки срабатывания.

> **См. также:**
>
> - [Функции PromQL](./functions.md) — подробное описание встроенных функций.
> - [Агрегация в PromQL](./aggregation.md) — модификаторы `by` и `without`.
> - [Поведение метрик в реальных сценариях](./real_world_behavior.md) — нюансы работы с репликами и рестартами.
