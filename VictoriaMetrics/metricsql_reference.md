# MetricsQL: язык запросов VictoriaMetrics

**Актуально для:** VictoriaMetrics v1.154.x (Community) / v1.148.x (LTS)

## Определения

**MetricsQL** — язык запросов VictoriaMetrics, полностью обратно совместимый с PromQL, но расширенный: добавляет функции для работы с пропусками и аномалиями, предсказания, агрегации по диапазону (`range_*`), роллап-функции с произвольным окном и более удобный синтаксис литералов.

**Query Range** — диапазон времени, выбираемый синтаксисом `[5m]` у селектора. Расширяется «на лету» для роллап-функций.

**Rollup-функция** — функция вида `xxx_over_time` или `rollup_xxx`, вычисляющая агрегат по окну вперед/назад от каждой точки графика (в отличие от PromQL, где `xxx_over_time` вычисляется один раз на весь возвращаемый диапазон).

**Агрегатная функция** — `sum over (q) by ...`, `avg by (label)`, `topk`, `quantile` и т.п., применяемая между сериями (межсерийная агрегация), отличная от роллапа (внутрисерийная).

## Базовые концепции

### Архитектура выполнения запроса

```
{instance=~"web-.*"}   →   выбор серии по селектору (регексп, как в PromQL)
        │
        ▼
   [5m]                 →   расширение временного окна/шага
        │
        ▼
   rate(...)            →   роллап-функция: агрегат по окну
        │
        ▼
   sum by (job) (...)   →   агрегация между сериями
        │
        ▼
   график / алерт / recording rule
```

Ключевое отличие от PromQL: в PromQL функция `rate(x[5m])` возвращает столько точек, сколько диапазонов 5m укладывается в запрошенный интервал. MetricsQL вычисляет значение в **каждой точке** графика, используя окно перед точкой. Отсюда — более гладкие и корректные графики без потери точек на старте.

### Совместимость с PromQL

- Каждый корректный PromQL-запрос — корректный MetricsQL-запрос.
- Можно смешивать PromQL-функции и MetricsQL-функции в одном выражении.
- В vmui (UI VictoriaMetrics) поддерживается «прощающий» режим с оператором `|` (pipe): `rate( |foo)` автоматически подставит нужный тайм-селектор, а неизвестные функции не будут ошибкой.
- MetricsQL учитывает последний сырой образец **до** окна для `rate`/`increase` (в отличие от Prometheus, который его упускает) — `increase(m[$__interval])` возвращает ожидаемый результат без экстраполяции.

См. подробно: [PromQL: селекторы и операторы](../Prometheus/concepts/promql/selectors_operators.md), [PromQL: функции](../Prometheus/concepts/promql/functions.md).

### Роллап-функции

| PromQL | MetricsQL | Комментарий |
| :--- | :--- | :--- |
| `rate(x[5m])` | `rate(x)` | окно можно не указывать — подбирается из step и scrape_interval |
| `avg_over_time(x[5m])` | `avg_over_time(x)` | окно необязательно; то же для `min/max/sum/median/stddev/stdvar/count` |
| `quantile_over_time(0.9, x[5m])` | `quantile_over_time(0.9, x)` | |
| `sum_over_time(x[5m])` | `sum_over_time(x)` | окно задаётся аргументом; `rollup_sum` не существует |
| — | `rollup_rate(x[5m])` | возвращает min/max/avg одновременно (метки `rollup="min/max/avg"`) |
| `histogram_quantile` + bucketed | `histogram_over_time(x[5m])` | возвращает готовую гистограмму для последующего `histogram_quantile` |

Роллап-функции (полную справку — в [документации VM](https://docs.victoriametrics.com/victoriametrics/metricsql/)):

`absent_over_time`, `aggr_over_time`, `ascent_over_time`, `avg_over_time`, `changes`, `changes_prometheus`, `count_eq_over_time`, `count_gt_over_time`, `count_le_over_time`, `count_ne_over_time`, `count_over_time`, `count_values_over_time`, `decreases_over_time`, `default_rollup`, `delta`, `delta_prometheus`, `deriv`, `deriv_fast`, `descent_over_time`, `distinct_over_time`, `duration_over_time`, `first_over_time`, `geomean_over_time`, `histogram_over_time`, `hoeffding_bound_lower`, `hoeffding_bound_upper`, `holt_winters`, `idelta`, `ideriv`, `increase`, `increase_prometheus`, `increase_pure`, `increases_over_time`, `integrate`, `irate`, `lag`, `last_over_time`, `lifetime`, `mad_over_time`, `max_over_time`, `median_over_time`, `min_over_time`, `mode_over_time`, `outlier_iqr_over_time`, `predict_linear`, `present_over_time`, `quantile_over_time`, `quantiles_over_time`, `range_over_time`, `rate`, `rate_prometheus`, `rate_over_sum`, `resets`, `rollup`, `rollup_candlestick`, `rollup_delta`, `rollup_deriv`, `rollup_increase`, `rollup_rate`, `rollup_scrape_interval`, `scrape_interval`, `share_eq_over_time`, `share_gt_over_time`, `share_le_over_time`, `stale_samples_over_time`, `stddev_over_time`, `stdvar_over_time`, `sum2_over_time`, `sum_eq_over_time`, `sum_gt_over_time`, `sum_le_over_time`, `sum_over_time`, `tfirst_over_time`, `tlast_change_over_time`, `tlast_over_time`, `tmax_over_time`, `tmin_over_time`, `zscore_over_time`, `timestamp`, `timestamp_with_name`.

> `rollup_*` — семейство роллапов с 2-м аргументом (`min`/`max`/`avg`): `rollup_rate`, `rollup_delta`, `rollup_deriv`, `rollup_increase`, `rollup_scrape_interval`. `rollup_sum`/`rollup_avg`/`rollup_min`/`rollup_max` не существуют — для сумм/средних используйте `*_over_time(...)`.

### Range-функции `range_*` (агрегация внутри скользящего окна)

Общая форма: `range_avg(x)` и подвид с параметром `range_avg(x[5m])`. Отличие от обычных агрегатов: финальное значение **return-серий повторяет исходную форму** (т.е. переносит статистику окна в каждую точку), что удобно для нормализации и выбросов.

- `range_avg(x)`, `range_min(x)`, `range_max(x)`, `range_sum(x)`, `range_median(x)`, `range_mad(x)`, `range_stddev(x)`, `range_stdvar(x)`, `range_quantile(0.95, x)`, `range_zscore(x)`, `range_first(x)`, `range_last(x)`, `range_normalize(x)`, `range_linear_regression(x)`, `range_trim_spikes(x)`, `range_trim_outliers(x)`.

Пример: `range_max(rate(cpu_usage_total[5m]))` — показывает максимум скользящего окна в каждой точке, при этом функция видит только диапазон `[5m]` у аргумента и может подтягивать окно автоматически.

> `range_over_time(x[d])` — это **роллап** (max-min за окно), а не range-функция; перепутать с `range_*` не стоит.

### Пайплайн-оператор и встроенные формы записи

```
rate({__name__=~"http_requests.*"}) | 1   # для понимания на месте
| alias("requests_per_sec")               # переименовать серию
```

Специальные формы:
- `sum(rate(x))` без указания окна — окно подхватывается из `-search.latencyOffset` и шага.
- `label_set(labels, key, value)`, `label_del`, `label_keep`, `label_map`, `label_copy`, `label_move` — работа с метками как с функциями.
- `time()`, `now()`, `start()`, `end()`, `step()`, `sstep()` — значения запроса.

### WITH-шаблоны (именованные подвыражения)

```promql
WITH (
  input = (metric)
  rateInput = (rate(input))
  sumRate = (sum(rateInput))
) sumRate
```

Здесь `input` — параметр-выражение (может ссылаться на другие именованные выражения), `rateInput` — результат применения функции, `sumRate` — финальный результат. Удобно для читаемых сложных запросов (основа для «приведения к стандарту» в recording rules). См. [Recording rules](../Prometheus/concepts/recording_rules.md).

### Синтаксис с «ленивым» диапазоном

Распространённая путаница — окно в аргументе vs. окно селектора:

```promql
# Окно до точки — сумма за последние 5 минут перед каждой точкой:
sum_over_time(x[5m])

# Сработает для среднего за 5 минут до каждой точки:
range_avg(x[5m])
```

Для серий с пропусками используйте `default_rollup(x)` — она заполняет пропуски значением из предыдущих точек (без «обрезания» графика по краям).

### Native Histograms и `vmrange`: практика

Prometheus Native Histograms (с v1.143.0) в VictoriaMetrics конвертируются во внутренний формат с лейблами **`vmrange`** (сервисы-«бины»). Это экономнее места, но важно знать, как к ним работать:

```promql
# histogram_quantile НАПРЯМУЮ работает с vmrange-гистограммами:
histogram_quantile(0.99, rate(request_duration_seconds_histogram[5m]))

# Каноничный паттерн для гистограмм-гаугж:
histogram_quantile(0.5, sum(histogram_over_time(temperature[24h])) by (vmrange,country))
```

Практика:

- `histogram_quantile` **прозрачно** обрабатывает buck-схемы с `vmrange`-лейблом (не требует ручной конвертации);
- для тепловых карт в Grafana (которая не понимает `vmrange`) используйте `prometheus_buckets(metric_bucket)` — он переводит `vmrange` → `le`-метки;
- не смешивайте в одной панели серии **native** (с `vmrange`) и **classic bucketed** (`le=...`) гистограммы — их границы бакетов разные, и `histogram_quantile` даст усреднённый, неверный результат;
- чтобы проверить тип, посмотрите метки серии (`vmrange` — native, `le` — classic);
- для `vmrange`-серий допустимы aggregate-функции `histogram_avg`, `histogram_quantiles` и т.п. (см. документацию).

### Staleness и пропуски данных

**Окно lookbehind по умолчанию.** Если `[...]` у роллап-функции не указано, VictoriaMetrics подбирает окно по фактическим данным. Для range-запросов реальный интервал между сэмплами определяется как **медиана интервалов между последними 20 сырыми сэмплами** в выбранном диапазоне — так пропущенный скрейп заполняется предыдущим значением, а устаревшие серии обнаруживаются без жёсткого пяти минутного lookback, принятого в Prometheus. Для `default_rollup` и `rate` без явного окна действует `max(step, scrape_interval)` — это защищает от ложных дыр, когда `step` графика меньше интервала скрейпа.

**Staleness-маркеры.** При исчезновении цели скрейпер записывает stale NaN — ряд немедленно помечается устаревшим, не дожидаясь истечения окна. `default_rollup` учитывает такие маркеры при выборе последнего значения, `last_over_time` — нет.

Диагностика пропусков:

```promql
# Сколько staleness-маркеров в окне (дыры из-за пропавших таргетов?)
stale_samples_over_time(up[1h])

# Фактический интервал между сэмплами серии за окно
scrape_interval(up[1h])
```

Флаги, влияющие на поведение:

| Флаг | Где | Действие |
| :--- | :--- | :--- |
| `-search.latencyOffset` | vmselect / vmsingle | Сколько недавно записанных сэмплов скрыто от запросов (по умолчанию `30s`); компенсируется `-rule.evalDelay` в vmalert |
| `-search.minStalenessInterval` | vmselect / vmsingle | Минимальный интервал расчёта staleness; поднимите ближе к максимальному интервалу между сэмплами, если дыры на графиках вызваны нерегулярной записью |
| `-search.maxStalenessInterval` | vmselect / vmsingle | Максимальный интервал staleness; по умолчанию вычисляется из медианы интервалов между сэмплами |
| `-search.setLookbackToStep` | vmselect / vmsingle | Фиксирует lookback равным `step` запроса вместо адаптивного расчёта |
| `-search.noStaleMarkers` | vmsingle / vmselect | Не тратить CPU на обработку stale-маркеров, если база их не содержит |
| `-promscrape.noStaleMarkers` | vmagent | Не отправлять stale-маркеры при пропадании цели (экономия памяти); то же — опция цели `no_stale_markers: true` |

**Визуальное заполнение дыр** (не меняет данные): `keep_last_value(q)` — значение последней непустой точки, `interpolate` — интерполяция, `q1 default q2` — подстановка значений из второго запроса.

Поведение Prometheus (5-минутный lookback, stale markers) и сценарии детекции тихих отказов — [PromQL в реальных сценариях](../Prometheus/concepts/promql/real_world_behavior.md). Разбор, где именно пропали данные — [триаж цепочки сбора](./metrics-flow-troubleshooting.md#8-дыры-на-графиках-данные-есть-но-с-пропусками).

## Валидация установки

```bash
# В UI VictoriaMetrics: /vmui → вкладка Queries — введите выражение, ошибки синтаксиса подсветятся.

# Программная проверка через PromQL-совместимый /api/v1/query:
curl -s 'http://localhost:8428/api/v1/query?query=up' | jq '.status'
# → "success"

# Проверка, что выбранный метрик и метки видимы:
curl -s 'http://localhost:8428/api/v1/label/__name__/values' | jq '.data | length'
# >0 — метрики есть

# Проверка datasource через прокси Grafana:
curl -s "http://grafana:3000/api/datasources/proxy/uid/victoriametrics/api/v1/query?query=up" \
  -H "Authorization: Bearer <SA_TOKEN>" | jq '.status'
# → "success"
```

## Поиск и устранение неисправностей

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| Запрос медленный | Слишком широкая маска (`{__name__=~".*"}`), нет нужных фильтров | Сузить маску селектора; для кардинальности — [vmestimator](./vmestimator.md) |
| Функция неизвестна | Синтаксис PromQL-функции, которой нет в MetricsQL | Перенести на `range_*` или `*_over_time`; список в `/vmui` и в [документации](https://docs.victoriametrics.com/victoriametrics/metricsql/) |
| Окно не видно | `*_over_time` в MetricsQL трактуется как rollup, возвращая лишь конечную точку | Добавить явный `[5m]` в аргументе или использовать `rollup_xxx` |
| Out-of-bounds | Серия стартует позже начала запроса | MetricsQL не нужен `@`; используйте `keep_last_value`/`default_rollup` |
| Изменение масштаба | `range_normalize` без параметров | Указать уменьшение на величину `range_avg` в аргументе |
| Панель пуста, а `rate(metric)` в терминале растёт | Селектор попал в несколько серий с разными типами (счётчики vs гаугжи) | Разделить селекторы; для гаугжей — `avg_over_time`, для счётчиков — `rate`/`increase` |
| `histogram_quantile` рисует "плоскую" линию | Смешаны native (`vmrange`) и classic (`le`) гистограммы в одной панели | Разнести на разные панели; использовать `prometheus_buckets()` для перевода vmrange→le |
| Логи не подгружаются через proxy | URL VL недоступен из пода Grafana | `curl -v http://victorialogs:9428/select/logsql/ping` из пода Grafana |
| Метрики видны, а Alerting UI пуст | Не задан `-vmalert.proxyURL` | Добавить флаг vmsingle/vmselect — см. [vmalert_overview.md](./vmalert_overview.md) |

## Рекомендации по эксплуатации

- Считайте сложные статистики recording rule-ами, а не в каждом дашборде — экономит CPU vmselect и время разработки.
- Для кардинальных серий сначала проверяйте число серий запроса через `/api/v1/query` и `topk` (см. [vmestimator](./vmestimator.md)).
- Пользуйтесь `WITH`-шаблонами для переносимых выражений между дашбордами и правилами.
- Для гистограмм применяйте `histogram_over_time` + `histogram_quantile`, а не `histogram_quantile` вручную по bucketed-сериям.
- Фиксируйте `keep_metric_names` в recording rules, где имя метрики важно для алертинга — иначе имя может быть сброшено.

## Ограничения и особые случаи

- MetricsQL — дополнение к PromQL, но результат может отличаться на функциях, зависящих от шага (в Prometheus-реализации `increase` и `rate` есть баг «extrapolation», в MetricsQL его нет).
- `range_*`-функции видят всего один диапазон `[N]` у аргумента; с несколькими временными интервалами нужно явно задавать окно.
- Native Histograms поддерживаются при приёме с v1.143.0 (vmagent, vmsingle, `vminsert`) и конвертируются в серии с `vmrange`-лейблами; `histogram_quantile` работает с ними напрямую — [http_api_reference.md](./http_api_reference.md) описывает эндпоинты и порты.
- В Enterprise доступны дополнительные функции (например, `histogram_quantiles` и `aggr_over_time`) с повышенной нагрузкой на CPU — см. [enterprise_features.md](./enterprise_features.md).
- Плагин Grafana `victoriametrics-logs-datasource` требует отдельной установки; для метрик достаточно встроенного datasource `prometheus` или плагина `victoriametrics-metrics-datasource` — см. [grafana_integration.md](./grafana_integration.md).

## Дополнительная информация

### См. также

- [VictoriaMetrics: обзор](./overview.md);
- [PromQL: селекторы и операторы](../Prometheus/concepts/promql/selectors_operators.md);
- [PromQL: функции](../Prometheus/concepts/promql/functions.md);
- [Grafana: интеграция](./grafana_integration.md);
- [vmalert: правила алертинга](./vmalert_overview.md);
- [vmestimator: оценка кардинальности](./vmestimator.md);
- [HTTP API VictoriaMetrics](./http_api_reference.md) — эндпоинты и порты компонентов.

> **Отличия MetricsQL от PromQL** — в официальной [документации](https://docs.victoriametrics.com/victoriametrics/metricsql/). Кратко: MetricsQL учитывает последний сырой образец до окна для `rate`/`increase`, не экстраполирует результаты, возвращает непустые ответы при шаге меньше scrape_interval, оставляет имена метрик после функций, не меняющих смысл, и удаляет NaN-значения из вывода.
