# Нет данных: триаж цепочки сбора метрик (VictoriaMetrics)

**Актуально для:** VictoriaMetrics v1.154.x (Community)

## Определения

**Триаж** — пошаговая диагностика от симптома к месту отказа: сначала локализовать участок цепочки, затем углубляться только в него.

**Пайплайн метрик** — маршрут данных от источника до графика: экспортёр → скрейп (vmagent/Prometheus) → remote write → приём (`vminsert`) → хранилище (`vmstorage`/vmsingle) → чтение (`vmselect`) → Grafana.

**Partial response (`isPartial`)** — признак частичного ответа кластера VictoriaMetrics: часть узлов `vmstorage` недоступна, данные возвращены не полностью.

## Базовые концепции

### Где что может сломаться

```
[экспортёр :9100/metrics]
        │  1. процесс упал / порт закрыт
        ▼
[vmagent /targets]  ──── 2. scrape: relabel удалил цель, timeout, up=0
        │
        │  3. remote write: очередь, сетевые ошибки, снappy
        ▼
[vminsert]  ──── 4. приём: vm_rows_ignored_total, лимиты, недоступный vmstorage
        │
        ▼
[vmstorage / vmsingle]  ──── 5. запись: диск, read-only, retention
        │
        ▼
[vmselect]  ──── 6. чтение: частичные ответы, тяжёлые запросы, задержка видимости
        │
        ▼
[Grafana]  ──── 7. datasource, панель, переменные, диапазон времени
```

Типичные симптомы и первые шаги:

| Симптом | Где искать | Шаг |
| :--- | :--- | :--- |
| Нет данных в Grafana, но прямой запрос в VM работает | Datasource/панель Grafana | 7 |
| Прямой запрос в VM тоже пуст | Запись или чтение | 2–5 |
| Пропал один job или метрика | Скрейп, экспортёр, relabel | 1, 6 |
| Данные есть, но с дырами | Staleness, интервалы, пропуски scrape | 8 |
| Видны только старые данные | Запись остановилась (очередь, read-only, диск) | 4–5 |
| Кластер отвечает `"isPartial": true` | Недоступные узлы `vmstorage` | 9 |

Порядок важен: **сначала отделите Grafana от хранилища** (шаг 1), иначе можно час искать несуществующую проблему в TSDB.

## Практические сценарии

### 1. Прямой запрос минуя Grafana

```bash
# Есть ли конкретная метрика в хранилище вообще
curl -s 'http://vmsingle:8428/api/v1/query?query=up{job="node-exporter"}' | jq -r '.status, (.data.result | length)'
# → success
# → 0          ← данных нет: проблема «до» Grafana, идём к шагу 4

# Сколько метрик вообще есть в базе
curl -s 'http://vmsingle:8428/api/v1/label/__name__/values' | jq '.data | length'
# → 18432      ← >0: база живая, проблема в конкретном job/метрике
```

Если прямой запрос возвращает данные, а Grafana — нет: проверьте datasource ([подключение VM к Grafana](./grafana_integration.md)), UID datasource в панели, переменные и диапазон времени на панели (Time range перекрыл retention).

### 2. Состояние хранилища чтением

```bash
# Число активных серий: резкий обвал указывает на потерю данных, взрыв — на кардинальность
curl -s http://vmsingle:8428/api/v1/status/tsdb | jq '.data.totalSeries'
# → 1843200

# Запросы сейчас выполняются? (vmselect/vmsingle)
curl -s http://vmselect:8481/api/v1/status/active_queries | jq '.data | length'
# → 3
```

Тяжёлые и частые запросы смотрите в `/api/v1/status/top_queries` и в вкладке VMUI Top Queries — подробности в [HTTP API](./http_api_reference.md).

### 3. Запись: пишет ли хранилище

```bash
# Вставка идёт?
curl -s http://vmsingle:8428/metrics | grep -E '^vm_rows_(inserted|ignored)_total'
# → vm_rows_inserted_total 1.234567e+09
# → vm_rows_ignored_total 0          ← рост ignored = данные отбрасываются

# Диска хватает? (read-only включается при нехватке)
curl -s http://vmsingle:8428/metrics | grep '^vm_free_disk_space_bytes'
# → vm_free_disk_space_bytes 5.1e+10
```

`vm_rows_inserted_total` не растёт / `ignored` растёт — разбор в таблицах [Troubleshooting overview](./overview.md#поиск-и-устранение-неисправностей-troubleshooting). Read-only и переполнение диска — там же.

### 4. Доставка в хранилище (vmagent)

```bash
# Здоровье целей скрейпа: статус up/down и ошибки
curl -s http://vmagent:8429/targets | jq .
# → список таргетов, их статус UP/DOWN, ошибки

# Метрики потерь на remote write
curl -s http://vmagent:8429/metrics | grep -E '^vmagent_remotewrite_(errors_total|queue_blocked|samples_dropped_total|pending_data_bytes)'
# → vmagent_remotewrite_errors_total 0
# → vmagent_remotewrite_samples_dropped_total 0
```

Разбор: `errors_total` растёт — хранилище недоступно или отвечает ошибками; `queue_blocked=1` — backpressure, хранилище не успевает; `samples_dropped_total` растёт — данные теряются (очередь переполнена или выключена). Метрики и сценарии — [Самомониторинг vmagent](../Concepts/Observability_and_Monitoring/meta-monitoring.md#сценарий-2-самомониторинг-victoriametrics-vmagent), persistent queue — [vmagent: конфигурация](./vmagent_overview.md#3-persistent-queue-и-расчёт-места-под-буфер).

### 5. Источник: жив ли экспортёр

```bash
curl -s http://node-exporter:9100/metrics | head -3
# → # HELP node_cpu_seconds_total ...
```

Если `up == 0` в цепи vmagent — проблема на этом шаге: сеть, порт, firewall, relabel-правило, упавший процесс. Полный разбор `up == 0` — [Prometheus: сценарий 4](../Prometheus/troubleshooting.md#сценарий-4-up--0---target-недоступен) (механика идентична, vmagent использует ту же схему `up`/relabel).

### 6. Пропал конкретный job или метрика

1. `curl /targets` (шаг 4) — есть ли цель и в каком она состоянии.
2. Если цель есть, а данных нет — проверьте `relabel_configs`: не отбрасывается ли `job`/`instance`.
3. Метрика могла исчезнуть из-за деплоя (новая версия экспортера переименовала её) — сравните `/api/v1/label/__name__/values` до и после.
4. Для детекции полного отсутствия настройте алерт:

```promql
absent_over_time(up{job="critical-service"}[15m])
```

### 7. Datasource Grafana

Когда прямой запрос работает: убедитесь, что datasource указывает на `vmselect`/`vmsingle` и использует правильный тип плагина ([Два плагина: Prometheus против VictoriaMetrics](./grafana_integration.md#два-плагина-для-метрик-prometheus-против-victoriametrics-datasource)), URL без лишнего префикса tenants ([URL-адреса](./grafana_integration.md#какие-url-адреса-указывать)), и что на панели нет ошибки запроса (откройте Inspect → Query).

### 8. Дыры на графиках (данные есть, но с пропусками)

Причина — не в потере данных, а в поведении чтения: окно lookbehind, staleness-маркеры, нерегулярный интервал. Механика VictoriaMetrics (медианный lookbehind, заполнение пропущенных скрейпов, флаги `-search.minStalenessInterval` / `-search.maxStalenessInterval`, `-search.latencyOffset`) — [Staleness и пропуски данных](./metricsql_reference.md#staleness-и-пропуски-данных). Поведение в самом Prometheus — [PromQL в реальных сценариях](../Prometheus/concepts/promql/real_world_behavior.md).

Проверить, являются ли дыры staleness-маркерами:

```promql
stale_samples_over_time(up{job="node-exporter"}[1h])
```

### 9. Кластер: частичные ответы

Если `vmselect` возвращает `"isPartial": true`, часть узлов `vmstorage` недоступна и данные неполные — визуально это выглядит как «пропали метрики с такого-то времени» или пустые панели для части тенантов. Проверьте `/health` всех `-storageNode`, логи `vminsert` (`vm_rpc_*`) и при необходимости включите `-search.denyPartialResponse`, чтобы видеть ошибку вместо тихо неполного ответа. Подробнее: [Ограничения кластера](./cluster_operations.md#ограничения-и-особые-случаи).

## Рекомендации по эксплуатации

- **Синтетика обязательна**: всегда скрейпьте `up` по каждому job — без него «пропал экспортёр» и «пропал scrape» неразличимы.
- **Watchdog/Dead Man's Switch снаружи стека**: метрика, которая должна ровно писаться каждые N минут, и алерт по её отсутствию. Это ловит отказ всего конвейера, включая саму VictoriaMetrics: [Внешний watchdog](../Concepts/Observability_and_Monitoring/meta-monitoring.md#сценарий-9-внешний-watchdog-на-bare-metal-healthchecksio-self-hosted), [Monitoring pipeline](../Concepts/Observability_and_Monitoring/meta-monitoring.md) (Сценарий 10 — мониторинг бэкапов).
- **Алерт «метрика пропала»** стройте через `absent_over_time(...)` для критичных series и через `up == 0` для таргетов; комбинация покрывает оба типа отказа.
- **Retention и компакция**: «пропали старые данные» почти всегда retention (`-retentionPeriod`) или ручное удаление — сверьтесь с [retention в overview](./overview.md#retention-и-управление-данными).
- **Фиксируйте runbook**: каждая строка этого чек-листа должна вести на конкретную команду — так диагностику сможет выполнить дежурный без знания стека.

## Ограничения и особые случаи

- **Задержка видимости**: данные, записанные < 30 s назад, могут не отвечать на запросы (`-search.latencyOffset`) — не спешите диагностировать потерю в первые секунды после записи.
- **Частичные ответы кластера** — отдельный класс «пропажи»: данные существуют, но часть узлов недоступна; ищите `isPartial`, а не scrape.
- **Read-only режим**: при нехватке диска запись останавливается, запросы продолжают работать — панели выглядят живыми, но новые данные не появляются.
- **Диагностика самой VictoriaMetrics не должна зависеть от неё**: минимум — внешний watchdog и возможность прочитать `/metrics` компонентов напрямую (см. [Самомониторинг стека](./self-monitoring.md)).

## Дополнительная информация

Смотрите также:

* [VictoriaMetrics: обзор](./overview.md) — таблицы Troubleshooting single/cluster;
* [Prometheus: troubleshooting](../Prometheus/troubleshooting.md) — методология для Prometheus-стека (сценарии 4, 6, 9 перекликаются с VM);
* [vmagent: обзор](./vmagent_overview.md) — `/targets`, persistent queue, режимы доставки;
* [HTTP API](./http_api_reference.md) — tsdb status, active/top queries, экспорт;
* [Staleness и пропуски данных](./metricsql_reference.md#staleness-и-пропуски-данных) — почему на графиках дыры;
* [Самомониторинг стека](./self-monitoring.md) — метрики и алерты компонентов VictoriaMetrics;
* [Мета-мониторинг](../Concepts/Observability_and_Monitoring/meta-monitoring.md) — концепция и сценарии для всего стека;
* [Grafana: интеграция](./grafana_integration.md) — datasource, URL, плагины.
