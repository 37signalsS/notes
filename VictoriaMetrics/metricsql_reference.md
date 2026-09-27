# MetricsQL: язык запросов VictoriaMetrics

## Определения

**MetricsQL** — язык запросов VictoriaMetrics, полностью обратно совместимый с PromQL, но расширенный: добавляет функции для работы с пропусками и аномалиями, предсказания, агрегации по диапазону (`range_*`), роллап-функции с произвольным окном и более удобный синтаксис литералов.

**Query Range** — диапазон времени, выбираемый синтаксисом `[5m]` у селектора. Расширяется «на лету» для роллап-функций.

**Rollup-функция** — функция вида `xxx_over_time` или `rollup_xxx`, вычисляющая агрегат по окну вперед/назад от каждой точки графика (в отличие от PromQL, где `xxx_over_time` вычисляется один раз на весь возвращаемый диапазон).

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

См. подробно: [PromQL в этом вольте](../Prometheus/concepts/promql/selectors_operators.md), [functions](../Prometheus/concepts/promql/functions.md).

## Практические сценарии

### Роллап-функции (замена `*_over_time` из PromQL)

| PromQL | MetricsQL | Комментарий |
| :--- | :--- | :--- |
| `rate(x[5m])` | `rate(x)` | окно можно не указывать |
| `avg_over_time(x[5m])` | `avg_over_time(x)` | то же для `min/max/sum/median/stddev/stdvar/count` |
| `quantile_over_time(0.9, x[5m])` | `quantile_over_time(0.9, x)` | |
| `sum_over_time(x[5m])` | `rollup_sum(x)` | окно задается аргументом |
| — | `rollup_rate(x[5m])` | возвращает min/max/avg одновременно |
| `histogram_quantile` + bucketed | `histogram_over_time(x[5m])` | возвращает готовую гистограмму |

Роллап-функции: `avg_over_time`, `sum_over_time`, `min/max_over_time`, `median_over_time`, `mad_over_time`, `mode_over_time`, `stddev/stdvar_over_time`, `count_over_time`, `changes_over_time`, `delta_over_time`, `increase_over_time`, `rate_over_time`, `irate`, `deriv`, `predict_linear`, `holt_winters`, `first/last_over_time`, `tmin/tmax_over_time`, `tfirst/tlast_change_over_time`, `distinct_over_time`, `geomean_over_time`, `share_gt/le/eq_over_time`, `count_gt/le/ge/lt/eq/ne_over_time`, `ascent/descent_over_time`, `idelta_over_time`, `integrate`, `zscore_over_time`, `aggregate`, `rollup_*` (в т.ч. `rollup_rate`, `rollup_avg`).

### Range-функции `range_*` (агрегация внутри скользящего окна)

Общая форма: `range_avg(x)` и подвид с параметром `range_avg(x[5m])`. Отличие от обычных агрегатов: финальное значение **return-серий повторяет исходную форму** (т.е. переносит статистику окна в каждую точку), что удобно для нормализации и выбросов:

- `range_avg(x)`, `range_min(x)`, `range_max(x)`, `range_sum(x)`, `range_median(x)`, `range_mad(x)`, `range_stddev(x)`, `range_stdvar(x)`, `range_quantile(0.95, x)`, `range_zscore(x)`, `range_count(x)`, `range_first(x)`, `range_over_time(x)`, `range_normalize(x)`, `range_linear_regression(x)`, `range_linear_slope(x)`, `range_linear_intercept(x)`, `range_missed(x)`, `range_trim_spikes(x)`, `range_trim_outliers(x)`.

Пример: `range_max(rate(cpu_usage_total[5m]))` — показывает максимум скользящего окна в каждой точке, при этом функция видит только диапазон `[5m]` у аргумента и может подтягивать окно автоматически.

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

Распространенная путаница — окно в аргументе vs. окно селектора:

```promql
# Окно до точки — сумма за последние 5 минут перед каждой точкой:
sum_over_time(x[5m])

# Сработает для среднего за 5 минут до каждой точки:
rollup_avg(x, 5m)
```

Для серий с пропусками используйте `default_rollup(x)` — она заполняет пропуски значением из предыдущих точек (без «обрезания» графика по краям).

### Native Histograms и `vmrange`: практика

Prometheus Native Histograms (с v1.143.0) в VictoriaMetrics конвертируются во внутренний формат с лейблами **`vmrange`** (сервисы-«бин»). Это экономнее места, но не все функции MetricsQL работают с такими сериями напрямую:

```promql
# НЕ работает для серии с vmrange честно (требует bucketed-гистограммы):
histogram_quantile(0.99, rate(request_duration_seconds_histogram[5m]))

# РАБОТАЕТ устойчиво: свёртка через histogram_over_time/quantile
histogram_over_time(request_duration_seconds_histogram[5m])
quantile_over_time(0.99, request_duration_seconds_histogram[5m])
```

Практика:

- Проверяйте, что экспортер отдаёт bucketed vs native-гистограммы (в VM они помечены `vmrange`-меткой);
- Для перцентильных вопросов используйте `histogram_over_time`/`quantile_over_time` — они учитывают `vmrange` автоматический;
- Не смешивайте в одной панели ряд native-гистограмм с классическими bucketed — результат квантли будет усреднённым между форматами;
- Отслеживайте расхождение через `sum(histogram_over_time(...))` vs. `histogram_quantile` с bucketed — признаки микс-данных.

## Валидация установки

```bash
# Проверка синтаксиса vmui: /vmui  →  вкладка Queries
# Служебные эндпоинты для отладки запросов:
curl -s 'http://localhost:8428/api/v1/label/__name__/values' | jq .
# Проверка, что expression ok (используется в /vmui и API):
curl -s "http://localhost:8428/vmui"
```

## Поиск и устранение неисправностей

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| Запрос медленный | Слишком широкая маска (`{__name__=~".*"}`), нет нужных фильтров | Сузить маску селектора; для кардинальности — [vmestimator](./vmestimator.md) |
| Функция неизвестна | Синтаксис PromQL-функции, которой нет в MetricsQL | Перенести на `range_*` или `*_over_time`; список в `/vmui` |
| Окно не видно | `*_over_time` в MetricsQL трактуется как rollup, возвращая лишь конечную точку | Добавить явный `[5m]` в аргументе или использовать `rollup_xxx` |
| Out-of-bounds | Серия стартует позже начала запроса | MetricsQL не нужен `@`; используйте `keep_last_value`/`default_rollup` |
| Изменение масштаба | `range_normalize` без параметров | Указать уменьшение на величину `range_avg` в аргументе |

## Рекомендации по эксплуатации

- Считайте сложные статистики recording rule-ами, а не в каждом дашборде — экономит CPU vmselect и время разработки.
- Для кардинальных серий сначала проверяйте число серий запроса через `/api/v1/query` и `topk` (см. [vmestimator](./vmestimator.md)).
- Пользуйтесь `WITH`-шаблонами для переносимых выражений между дашбордами и правилами.
- Для гистограмм применяйте `histogram_over_time` + `histogram_quantile`, а не `histogram_quantile` вручную по bucketed-сериям.

## Ограничения и особые случаи

- MetricsQL — дополнение к PromQL, но результат может отличаться на функциях, зависящих от шага (например, у Prometheus-реализации `increase` и `rate` есть баг «extrapolation», в MetricsQL его нет).
- `range_*`-функции видят всего один диапазон `[N]` у аргумента; с несколькими временными интервалами нужно явно задавать окно.
- Native Histograms поддерживаются начиная с v1.143.0; не все функции MetricsQL работают с `vmrange`-гистограммой — используйте `histogram_quantile` для совместимости.
- В Enterprise доступны дополнительные функции (например, `histogram_quantiles`) с повышенной нагрузкой на CPU.

## Дополнительная информация

### См. также

- [VictoriaMetrics: обзор](./overview.md);
- [PromQL: селекторы и операторы](../Prometheus/concepts/promql/selectors_operators.md);
- [vmalert: правила алертинга](./vmalert_overview.md).