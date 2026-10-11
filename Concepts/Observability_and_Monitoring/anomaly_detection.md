# Детекция аномалий (Anomaly Detection)

**Актуально для:** Prometheus 3.13.x / 3.14.x, Grafana Alerting 11.x, Zabbix 7.0 LTS / 7.4, Netdata 2.x, Linux 5.4+ (PSI)

## Определения

- **Аномалия (Anomaly)** — значение метрики или паттерн поведения, который значимо отклоняется от ожидаемого baseline, указывая на возможную проблему в системе.

- **Baseline (Базовый уровень)** — типичное поведение метрики в нормальных условиях, рассчитанное за исторический период.

- **Static Threshold (Статический порог)** — жестко заданное значение (например, `CPU > 90%`), не адаптирующееся к изменениям нагрузки или сезонности.

- **Dynamic Threshold (Динамический порог)** — порог, который автоматически пересчитывается на основе исторического baseline с учетом трендов и сезонности.

- **Outlier (Выброс)** — единичное значение, отклоняющееся от baseline. Может быть аномалией или шумом.

- **Seasonality (Сезонность)** — регулярные повторяющиеся паттерны в метриках (например, рост трафика в рабочее время, снижение в ночное).

- **Trend (Тренд)** — долгосрочное направление изменения метрики (рост, снижение, стагнация).

- **False Positive (Ложноположительный)** — алерт, сработавший при отсутствии реальной проблемы.

- **False Negative (Ложноотрицательный)** — пропуск реальной проблемы системой алертинга.

- **Sensitivity (Чувствительность)** — способность детектировать аномалии. Высокая чувствительность → больше false positives. Низкая чувствительность → больше false negatives.

- **PromQL Anomaly Functions** — набор функций Prometheus для детекции аномалий: `predict_linear()`, `deriv()`, `changes()`, `resets()`.

---

## Базовые концепции

### Почему статические пороги не работают

Статические пороги (`CPU > 90%`, `Latency > 1s`) имеют фундаментальные проблемы:

1. **Не учитывают сезонность:** Пиковая нагрузка днем при объеме заказов на 300% выше ночной может быть нормальной, но статический порог сработает как аномалия.

2. **Не адаптируются к росту системы:** При росте трафика в 2 раза старый порог для latency перестает быть релевантным.

3. **Разные baselines для разных дней:** Понедельник утром (рост после выходных) vs воскресенье вечером (спад).

4. **Зависимость от контекста:** CPU > 90% в 3 часа ночи при низком трафике — это аномалия. CPU > 90% в час пик при высокой нагрузке — это норма.

### Типы аномалий

| Тип | Описание | Пример | Метод детекции |
| :--- | :--- | :--- | :--- |
| **Point Anomaly** | Единичное значение отклоняется | Spike latency в 5 секунд | Z-score, IQR |
| **Contextual Anomaly** | Значение аномально в конкретном контексте | Высокая error rate ночью | Сезонный baseline |
| **Collective Anomaly** | Последовательность значений, не аномальных по отдельности | Рост latency на 20% в течение 10 минут | Trend detection, change point |
| **Seasonal Anomaly** | Отклонение от ожидаемого сезонного паттерна | Снижение заказов в Чёрную пятницу | Seasonal decomposition |

### Принципы эффективной детекции аномалий

1. **Измеряйте deviations, а не absolute values:** Вместо `latency > 1s` используйте `latency > baseline + 3σ`.

2. **Учитывайте контекст:** Сегодняшний понедельник ≠ вчерашнее воскресенье.

3. **Объединяйте сигналы:** Одна метрика редко дает полную картину. Коррелируйте latency, error rate, saturation.

4. **Адаптируйте пороги:** Используйте multiple windows (1h, 6h, 24h) для разных типов аномалий.

5. **Минимизируйте false positives:** Каждый ложный алерт снижает доверие к системе и увеличивает MTTR.

## Архитектура детекции аномалий

Пайплайн детекции состоит из пяти этапов:

```
Сбор метрик/логов → Расчет baseline → Детекция отклонения → Фильтрация шума → Алерт / тикет
```

1. **Collection (Сбор):** Экспорт метрик через `node_exporter`, `process_exporter`, `postgres_exporter` и другие экспортёры. Период сбора (scrape interval) влияет на задержку детекции: 15s = быстрая детекция, но выше нагрузка; 60s = консервативно.

2. **Baseline Calculation (Расчет базовой линии):** Вычисление среднего, перцентилей и стандартного отклонения за окно (1h, 6h, 24h, 7d). Для сезонных метрик — за тот же час/день неделю назад (`offset 1w`). Baseline хранится в TSDB (Prometheus) или пересчитывается на лету через recording rules.

3. **Detection (Детекция):** Сравнение текущего значения с baseline. Методы: Z-score, IQR, seasonal comparison, trend detection. Детекция может выполняться на стороне Prometheus (alerting rules) или на стороне внешней системы (Grafana Alerting, Zabbix triggers).

4. **Noise Filtering (Фильтрация):** Устранение кратковременных выбросов через `for` duration (5–10 минут), корреляция нескольких метрик (latency + errors + saturation одновременно), исключение известных событий (деплои, нагрузочное тестирование).

5. **Response (Реагирование):** Алерт в Alertmanager → маршрутизация по severity → runbook → RCA. Каждый алерт обязан иметь документацию (runbook_url) и владельца сервиса.

**Критически важные зависимости:**
- **NTP:** Рассинхронизация часов ломает сезонное сравнение и `offset 1w`.
- **Scrape reliability:** Пропуски scrapes (scrape timeout, target down) создают дыры в baseline. Используйте `absent()` для алертов на потерю метрик.
- **Label consistency:** Сезонный baseline ломается, если метка `job` или `instance` меняется между неделями. Используйте стабильные лейблы.

---

## Методы детекции аномалий

### Статистические методы

#### Z-Score (Стандартное отклонение)

Определяет, сколько стандартных отклонений значение удалено от среднего.

```promql
# Z-score для HTTP latency (P99)
# Вычисляется rolling mean и stddev за 1 час
(
  histogram_quantile(0.99, rate(http_request_duration_seconds_bucket[5m]))
  -
  avg_over_time(histogram_quantile(0.99, rate(http_request_duration_seconds_bucket[5m]))[1h:1m])
)
/
stddev_over_time(histogram_quantile(0.99, rate(http_request_duration_seconds_bucket[5m]))[1h:1m])
> 3
```

**Когда использовать:** Метрики с нормальным распределением, небольшой историей (1–7 дней).

**Ограничения:** Не работает с сезонностью, чувствителен к выбросам в baseline.

#### IQR (Interquartile Range)

Определяет аномалии как значения за пределами 1.5 * IQR от Q1/Q3. Подходит для skewed распределений с выбросами.

```promql
# Верхняя граница IQR (upper whisker) за 1 час
# Q3 = 75-й перцентиль, Q1 = 25-й перцентиль
# Аномалия: текущее значение > Q3 + 1.5 * IQR
request_rate > (
  quantile_over_time(0.75, request_rate[1h])
  + 1.5 * (
    quantile_over_time(0.75, request_rate[1h])
    - quantile_over_time(0.25, request_rate[1h])
  )
)
```

```yaml
# Alerting rule
- alert: HighRequestRateIQR
  expr: request_rate > (quantile_over_time(0.75, request_rate[1h]) + 1.5 * (quantile_over_time(0.75, request_rate[1h]) - quantile_over_time(0.25, request_rate[1h])))
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "Request rate exceeds IQR upper bound"
```

**Когда использовать:** Метрики с skewed распределением, наличие выбросов в истории.

#### Moving Average (Скользящее среднее)

Сравнивает текущее значение со скользящим средним за период.

```promql
# Аномалия: текущее значение > moving average + 2σ
(
  rate(http_requests_total[5m])
  >
  avg_over_time(rate(http_requests_total[5m])[30m:1m])
  + 2 * stddev_over_time(rate(http_requests_total[5m])[30m:1m])
)
```

**Когда использовать:** Быстрая реакция на изменения, метрики без сезонности.

#### Counter Anomalies: `changes()` и `resets()`

Для метрик-счетчиков (counters) аномалии часто проявляются как неожиданные скачки или сбросы.

```promql
# changes(): количество изменений значения за 5 минут
# Аномалия: >10 скачков за 5 минут — возможен флапинг или burst
changes(http_requests_total[5m]) > 10
```

```promql
# resets(): количество сбросов счетчика за 5 минут
# Аномалия: любой сброс (restart приложения, redeploy)
resets(http_requests_total[5m]) > 0
```

**Когда использовать:** Counters (requests, errors, bytes). Обнаруживает restart приложения, флапинг конфигурации, burst-трафик.

### Сезонная детекция

#### Seasonal Baseline

Учитывает недельные/дневные паттерны.

```promql
# Baseline: среднее значение за прошлую неделю в тот же день и час
avg_over_time(
  rate(http_requests_total[5m])
  [1w:1w] offset 1w
)
# Сравнение с текущим значением
rate(http_requests_total[5m]) > 1.5 * avg_over_time(
  rate(http_requests_total[5m])
  [1w:1w] offset 1w
)
```

**Когда использовать:** Метрики с выраженной сезонностью (трафик, CPU в рабочие часы).

#### Линейная регрессия (Linear Regression)

Прогноз на основе текущего тренда. В Prometheus реализуется через `predict_linear()` — линейная регрессия по временному ряду за указанный окном.

```promql
# Предсказание на 1 час вперед на основе линейного тренда
predict_linear(
  rate(http_requests_total[1h])[30m:]
, 3600
) > rate(http_requests_total[5m]) * 2
```

---

## Практические сценарии

### Сценарий 1: Динамические пороги в Grafana Alerting

Grafana Alerting поддерживает динамические пороги через `n1ql` expressions или внешние evaluation.

```yaml
# provisioning/alerting/rules/dynamic-thresholds.yaml
groups:
  - name: dynamic_thresholds
    rules:
      - alert: HighErrorRateDynamic
        expr: |
          (
            rate(http_requests_total{status=~"5.."}[5m])
            /
            rate(http_requests_total[5m])
          )
          >
          (
            avg_over_time(
              (
                rate(http_requests_total{status=~"5.."}[5m])
                /
                rate(http_requests_total[5m])
              )[24h:1h]
            )
            + 3 * stddev_over_time(
              (
                rate(http_requests_total{status=~"5.."}[5m])
                /
                rate(http_requests_total[5m])
              )[24h:1h]
            )
          )
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Error rate exceeds dynamic threshold (3σ from 24h baseline)"
          runbook_url: "https://wiki.internal/runbooks/high-error-rate"
```

### Сценарий 2: Детекция сезонных аномалий

**Проблема:** Трафик в рабочие часы в 5 раз выше ночного. Статический порог `requests > 1000` срабатывает каждый день в 10:00.

**Решение:** Относительный порог относительно baseline в тот же час прошлой недели.

```promql
# Алерт: рост трафика на 50% относительно прошлой недели
rate(http_requests_total[10m])
>
1.5 * avg_over_time(rate(http_requests_total[10m])[1w:1w] offset 1w)
```

### Сценарий 3: Детекция аномалий в логах

**Проблема:** Метрики в норме, но пользователи сообщают об ошибках. Аномалия проявляется только в логах (всплеск 5xx, auth failures, panic в application log).

**Решение:** Используйте Loki/Promtail или прямой grep/journalctl для алертов на паттерны в логах.

```bash
# Алерт на всплеск 5xx в access log за 5 минут
grep -c ' 5[0-9][0-9] ' /var/log/nginx/access.log | \
  awk '{if ($1 > 50) print "CRITICAL: 5xx rate=" $1}'
```

```promql
# Через Loki: рост 5xx в течение 5 минут
sum(rate({job="nginx"} |= " 5" [5m])) > 50
```

---

## Лучшие практики

### Конфигурация алертов

1. **Начинайте с 3σ:** Для новых сервисов используйте 3 стандартных отклонения как начальный порог. При необходимости настройте sensitivity.

2. **Используйте `for` duration:** Минимум 5–10 минут для фильтрации кратковременных выбросов.

3. **Комбинируйте методы:** Не полагайтесь только на статические пороги. Добавьте динамические baseline и seasonal correction.

4. **Коррелируйте сигналы:** Одиночный алерт на аномалию latency может быть шумом. Если одновременно аномальны error rate и saturation — это сигнал.

5. **Настройте silence strategically:** Известные плановые работы (деплои, нагрузочное тестирование) должны автоматически создавать silences.

### Валидация детекции

```bash
# Проверка, что алерт срабатывает на исторических аномалиях
# Используйте Prometheus recording rules для бэктестинга
# Пример: проверка за последние 7 дней
curl -s 'http://prometheus:9090/api/v1/query_range?query=ALERTS{alertname="HighErrorRateDynamic"}&start=7d&end=now&step=1h' | jq '.data.result'
```

### Обучение baseline

- **Cold start problem:** Для нового сервиса нет истории. Используйте conservative пороги или manual baseline первые 7–14 дней.
- **Обновление baseline:** Пересчитывайте baseline раз в неделю/месяц, чтобы адаптироваться к изменениям в системе.
- **Исключайте инциденты из baseline:** Время инцидентов искажает baseline. Используйте `ALERTS` для исключения периодов с активными инцидентами.

---

## Инструменты

| Категория | Инструменты | Метод детекции |
| :--- | :--- | :--- |
| **Prometheus** | Recording rules, `predict_linear()`, `deriv()` | Статистические, трендовые |
| **Grafana Alerting** | Dynamic thresholds, No-data / Null-value handling | Статические + relative thresholds |
| **Zabbix** | Triggers, иерархические хосты, preprocessing | Статистические, percentile-based |
| **Netdata** | Anomaly detection built-in | Statistical, per-metric |
| **Loki / Promtail** | LogQL pattern alerts | Log-based, frequency-based |
| **Custom (Python/bash)** | pandas, numpy, journalctl, grep | Статистические, полный контроль |

---

## Граничные случаи

### Высоконагруженные системы

**Проблема:** 100k+ метрик, миллионы событий в секунду. Статистические методы на каждом запросе слишком дорогие.

**Решение:**
- Используйте recording rules для предварительного вычисления baseline.
- Агрегируйте метрики на ingestion layer.
- Sampling для логов (1–10% при высоком объеме).

### Multi-tenant окружения

**Проблема:** Разные tenant имеют разные baseline. Один порог не подходит для всех.

**Решение:**
- Per-tenant baseline: `avg_over_time(metric{tenant="A"}[1h])`.
- Используйте `by (tenant)` в PromQL.
- Отдельные алерты на каждый tenant или percentile-based alerting.

### Change points (Изменение тренда)

**Проблема:** После деплоя или изменения конфигурации baseline смещается. Детектор считает новое состояние аномалией.

**Решение:**
- Исключайте периоды deployment из baseline.
- Используйте change point detection (библиотеки: ruptures, changefinder).
- Вручную пересчитывайте baseline после major changes.

### Seasonal holidays

**Проблема:** Чёрная пятница, распродажи, глобальные события создают extreme baseline.

**Решение:**
- Исключайте известные event days из baseline.
- Используйте manual overrides для known events.
- Создавайте calendar-based exceptions.

## Устранение неполадок

### Alert Fatigue: слишком много ложных алертов

**Симптомы:** Дежурный игнорирует алерты, инциденты подтверждаются в 1% случаев.

**Диагностика:**
```bash
# Проверка количества алертов за последние 24 часа
curl -s 'http://prometheus:9090/api/v1/query?query=ALERTS&time=now' | jq '[.data.result[] | select(.value[1] > 0)] | length'
```

**Решение:**
- Повысьте порог до 3σ (вместо 2σ).
- Добавьте `for: 10m` вместо `for: 0m`.
- Используйте percentile-based alerting вместо absolute thresholds.
- Группируйте алерты по `alertname` + `service`, избегайте группировки по `instance`.

### Baseline contaminated during incidents

**Симптомы:** После инцидента baseline "плавает", новые аномалии не детектируются или детектируются с задержкой.

**Диагностика:**
```bash
# Проверка, что в baseline попали периоды с инцидентами
# Сравните распределение метрики в "нормальные" и "инцидентные" периоды
```

**Решение:**
- Исключайте периоды с активными инцидентами из baseline через `ALERTS`:
  ```promql
  avg_over_time(metric[1h] unless ALERTS{alertname="HighErrorRate"}[1h])
  ```
- Пересчитывайте baseline после инцидента вручную.
- Используйте separate recording rules для baseline, чтобы можно было их обновлять без перезапуска алертов.

### Missing data / scrape failures

**Симптомы:** Метрика пропадает на 10 минут, детектор считает это аномалией или игнорирует.

**Диагностика:**
```promql
# Проверка, что up == 0 для target
up{job="node_exporter"} == 0
```

**Решение:**
- Настройте алерт `up == 0` для критичных сервисов.
- В правилах детекции используйте `absent_over_time()` для проверки наличия данных за период, или условие `or absent() == 0`, чтобы пропуски не создавали ложные алерты.
- В Grafana Alerting настройте No-data / Null-value handling на "No alert" или "Time no data to alert".

### Seasonal baseline broken by label changes

**Симптомы:** `offset 1w` возвращает пустые результаты или несоответствующие серии.

**Диагностика:**
```bash
# Проверка, что метки стабильны за неделю
curl -s 'http://prometheus:9090/api/v1/label/__name__/values' | jq '.data[] | select(. == "http_requests_total")'
```

**Решение:**
- Используйте стабильные лейблы (`job="api", method="POST", route="/payments"` вместо `instance="10.0.0.1:8080"`).
- Для сезонного baseline исключите high-cardinality лейблы:
  ```promql
  avg_over_time(rate(http_requests_total{job="api", method="POST"}[5m])[1w:1w] offset 1w)
  ```

### Change point: shift after deploy or config change

**Симптомы:** После деплоя детектор считает новое состояние аномалией, пока baseline не адаптируется.

**Диагностика:**
```bash
# Поиск изменений в конфигурации или деплоях
kubectl rollout history deployment/api --namespace=prod
```

**Решение:**
- Создавайте silence на период деплоя (5–10 минут) через Alertmanager inhibit rules или `for` duration.
- Исключайте deployment windows из baseline.
- После major changes (миграция БД, новый экземпляр) пересчитывайте baseline вручную.

---

## См. также

- **[Методология мониторинга](./monitoring_methodologies.md)** — USE/RED/Golden Signals, baseline establishment.
- **[Рекомендации по алертингу](./monitoring_alerting_recommendations.md)** — multi-window Burn Rate, alert fatigue mitigation.
- **[Метрики глубокий dive](./metrics_deep_dive.md)** — типы метрик, агрегация, процентили.
- **[Meta-Monitoring](./meta-monitoring.md)** — мониторинг самой системы мониторинга.
- **[Концепции SRE](../sre_concepts_main.md)** — SLO/SLI/SLA, error budgets.
