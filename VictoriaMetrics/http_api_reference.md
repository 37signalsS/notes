# VictoriaMetrics: справочник HTTP API и практика

**Актуально для:** VictoriaMetrics v1.154.x (Community) / v1.148.x (LTS)

## Определения

**HTTP API VictoriaMetrics** — набор endpoint-ов на `httpListenAddr` для записи, чтения, администрирования и диагностики. Для single-node всё висит на одном порту (по умолчанию `8428`); в кластере запись идёт в `vminsert` (`8480`), чтение — в `vmselect` (`8481`), служебные эндпоинты — в `vmstorage` (`8482`).

**Префиксы кластера** — `/insert/<accountID>/<projectID>/prometheus/...` (запись) и `/select/<accountID>/<projectID>/prometheus/...` (чтение). С v1.150.0 тенант также можно передавать через HTTP-заголовки `AccountID`/`ProjectID` (см. [overview](./overview.md)). В single-node тенант не указывается.

**Native-протокол** (`/api/v1/export/native`, `/api/v1/import/native`) — бинарный формат VictoriaMetrics для переноса данных между своими инстансами без перекодировки (используется в [vmctl](./vmctl_migration.md)). Самый быстрый способ миграции.

**Prometheus Remote Write** — протокол приёма данных Prometheus (snappy-сжатый Protobuf), используемый для интеграции с Prometheus и [vmagent](./vmagent_overview.md). Конечный путь: `/api/v1/write`.

**Prometheus querying API** — набор endpoint-ов, совместимых с [Prometheus HTTP API](../Prometheus/prometheus_api.md): `/api/v1/query`, `/api/v1/query_range`, `/api/v1/series`, `/api/v1/labels`, `/api/v1/label/<name>/values`, `/api/v1/metadata`, `/federate`. В VictoriaMetrics также доступен с префиксом `/prometheus/` (например, `/prometheus/api/v1/query`).

## Базовые концепции

### Архитектура и модель адресов

В single-node все эндпоинты доступны на одном порту (`-httpListenAddr`, по умолчанию `8428`). В кластере запросы распределяются по компонентам:

| Компонент | Порт | Назначение |
| :--- | :--- | :--- |
| `vmsingle` | `8428` | Приём, хранение, запросы, UI |
| `vminsert` | `8480` | Приём данных (remote write, import) |
| `vmselect` | `8481` | Запросы (query, query_range, export, delete) |
| `vmstorage` | `8482` | Хранилище: снапшоты, force_merge, force_flush |

Пути в кластере включают префикс тенанта:
- Запись: `/insert/<accountID>/<projectID>/prometheus/...`
- Чтение: `/select/<accountID>/<projectID>/prometheus/...`

### Группы эндпоинтов

| Группа | Примеры | HTTP-метод | Назначение |
| :--- | :--- | :--- | :--- |
| Запросы (Prometheus API) | `/api/v1/query`, `/api/v1/query_range`, `/api/v1/series`, `/api/v1/series/count`, `/api/v1/labels`, `/api/v1/label/<name>/values`, `/api/v1/metadata`, `/federate` | GET, POST | Мгновенные и диапазонные запросы, поиск серий, метаданные |
| Приём данных | `/api/v1/write`, `/api/v1/import`, `/api/v1/import/native`, `/api/v1/import/prometheus`, `/api/v1/import/csv`, `/api/v1/export` (обратно) | POST | Prometheus Remote Write, JSON line, native, Prometheus text, CSV |
| Экспорт данных | `/api/v1/export`, `/api/v1/export/csv`, `/api/v1/export/native` | GET, POST | Выгрузка: JSON-lines, CSV, бинарный native |
| Диагностика | `/api/v1/status/tsdb`, `/api/v1/status/active_queries`, `/api/v1/status/top_queries`, `/api/v1/status/buildinfo` | GET | Кардинальность, активные/частые запросы, версия |
| Управление данными | `/api/v1/admin/tsdb/delete_series` | POST | Удаление серий (только POST с v1.149.0) |
| Снапшоты | `/snapshot/create`, `/snapshot/list`, `/snapshot/delete`, `/snapshot/delete_all` | POST, GET | Создание, список, удаление снапшотов |
| Служебные (внутренние) | `/internal/force_merge`, `/internal/force_flush`, `/internal/resetRollupResultCache` | POST | Компакция, сброс in-memory, очистка кэша |
| Здоровье и статус | `/health`, `/-/healthy`, `/-/ready`, `/metrics`, `/flags`, `/-/reload`, `/vmui` | GET | Healthcheck, метрики, флаги, UI |

> В single-node export/import работают на `/api/v1/...`, в кластере — под префиксом тенанта: `/select/<ns>/<pid>/prometheus/api/v1/export` и `/insert/<ns>/<pid>/prometheus/api/v1/import`.

### Форматы ответов

API VictoriaMetrics возвращает JSON-ответы со следующей структурой:

```json
{
  "status": "success",
  "data": { ... }
}
```

При ошибке:

```json
{
  "status": "error",
  "errorType": "execution",
  "error": "1:1: parse error: unexpected char"
}
```

| Поле | Описание |
| :--- | :--- |
| `status` | `"success"` или `"error"` |
| `data` | Тело ответа (формат зависит от эндпоинта) |
| `errorType` | Категория ошибки: `bad_data`, `execution`, `server_error` |
| `error` | Текстовое описание ошибки |
| `warnings` | Нефатальные предупреждения |

### Форматы экспорта/импорта

**Экспорт:**

- `/api/v1/export` — экспорт в JSON-lines (по умолчанию). Каждая строка — JSON-объект с полями `metric` (имя + метки), `values` (значения) и `timestamps` (метки времени в мс). Подходит для выгрузки в пайплайны и миграции через сторонние утилиты.
- `/api/v1/export/csv` — экспорт в CSV с указанием порядка колонок через параметр `format`. Специальные имена: `__name__` (имя метрики), `__value__` (значение), `__timestamp__:unix_s` (timestamp).
- `/api/v1/export/native` — бинарный протокол: быстрый и плотный, используется vmctl. **Не** является публичным форматом — только VM↔VM.

**Импорт:**

- `/api/v1/import` — импорт в JSON-lines формате (см. ниже).
- `/api/v1/import/native` — импорт бинарного native формата (только VM↔VM).
- `/api/v1/import/prometheus` — загрузка текста Prometheus exposition (например, сохранённого scrape).
- `/api/v1/import/csv` — загрузка CSV с указанием порядка колонок (`format=N:type:name`).

**JSON line format** — каждая строка содержит JSON-объект:

```json
{"metric":{"__name__":"up","job":"node_exporter"},"values":[1,1],"timestamps":[1549891472010,1549891487724]}
```

Параметры:
- `match[]` — повторяемый параметр с PromQL-селектором для фильтрации (например, `match[]={__name__=~"node_.*"}`).
- `start`, `end` — диапазон времени (Unix timestamp в секундах/мс/мкс/нс, либо RFC3339).
- `reduce_mem_usage=1` — отключить дедупликацию при экспорте.
- `max_rows_per_line` — ограничить количество строк в каждой экспортированной строке.

**CSV формат** — параметр `format` описывает правила разбора колонок:

```
format=2:metric:ask,3:metric:bid,1:label:ticker,4:label:market
```

Каждое правило: `позиция_колонки:тип:имя`. Типы: `metric` (числовое значение), `label` (метка), `time` (временная метка: `unix_s`, `unix_ms`, `unix_ns`, `rfc3339`, `custom:layout`).

### Почему это важно знать на практике

Горячие сценарии эксплуатации — снапшоты ([vmbackup/vmrestore](./vmbackup_restore.md)), миграция ([vmctl](./vmctl_migration.md)) — построены поверх этих эндпоинтов: `/snapshot/create`, native-export. Диагностика кардинальности уже хранимых серий — `/api/v1/status/tsdb`, проактивная оценка по живому потоку — [vmestimator](./vmestimator.md). Понимание HTTP API позволяет делать перенос/выгрузку/чистку вручную, не запуская дополнительные утилиты.

## Практические сценарии

### 1. Экспорт данных (JSON-lines) с фильтром по времени и сериям

```bash
# Все серии node_* за последние сутки
curl -sG 'http://localhost:8428/api/v1/export' \
  --data-urlencode 'match[]={__name__=~"node_.*"}' \
  --data-urlencode 'start=20260921T00:00:00Z' \
  --data-urlencode 'end=20260922T00:00:00Z' \
  > export.jsonl

# Экспорт в кластере (тенант 0)
curl -sG 'http://vmselect:8481/select/0/prometheus/api/v1/export' \
  --data-urlencode 'match[]={__name__=~"node_.*"}' > export.jsonl
```

Ошибок нет — VM отдаёт 200 и потоки JSON-строк, по одной строке на временной ряд. Размер файла может быть большим: сужайте `match[]` и диапазон.

```bash
# Экспорт в CSV
curl -sG 'http://localhost:8428/api/v1/export/csv' \
  --data-urlencode 'format=__name__,job,instance,__value__,__timestamp__:unix_s' \
  --data-urlencode 'match[]={__name__="node_cpu_seconds_total"}' \
  --data-urlencode 'start=-1d' \
  > export.csv

# Экспорт в native-формате (бинарный)
curl -sG 'http://localhost:8428/api/v1/export/native' \
  --data-urlencode 'match[]={__name__="vm_http_request_errors_total"}' \
  --data-urlencode 'start=-1d' \
  -o data.native
```

### 2. Экспорт/импорт в native-формате (быстрая миграция вручную)

```bash
# Выгрузка native
curl -sG 'http://localhost:8428/api/v1/export/native' \
  --data-urlencode 'match[]={__name__=~"app_.*"}' \
  --data-urlencode 'start=2026-10-01T00:00:00Z' --data-urlencode 'end=2026-10-02T00:00:00Z' \
  -o data.native

# Загрузка на целевой инстанс (single-node)
curl -s http://localhost:8428/api/v1/import/native --data-binary @data.native

# В кластере — загрузка через vminsert с тенантом
curl -s http://vminsert:8480/insert/0/prometheus/api/v1/import/native --data-binary @data.native
```

Native-импорт быстрее JSON-lines в разы и не требует переиндексации на приёме. Для больших объёмов используйте [vmctl](./vmctl_migration.md) — он режет диапазоны на блоки и ретраит.

### 3. Кардинальность через `/api/v1/status/tsdb`

```bash
# Топ значений метки instance по количеству серий
curl -s 'http://localhost:8428/api/v1/status/tsdb' | jq '.data.labelValueCounters[] | select(.labelName=="instance")'
# → список (value, count) — самые «раздувающие» значения метки

# Топ метрик по количеству серий
curl -s 'http://localhost:8428/api/v1/status/tsdb?topN=10' | jq '.data.seriesCountByMetricName'

# Серии по фильтру
curl -sG 'http://localhost:8428/api/v1/series' \
  --data-urlencode 'match[]={job="api"}' | jq '.data | length'
```

`/api/v1/status/tsdb` поддерживает параметры:
- `topN=N` — количество топ записей (по умолчанию 10)
- `date=YYYY-MM-DD` — дата для сбора статистики (по умолчанию — текущий день)
- `focusLabel=LABEL_NAME` — возвращает значения выбранной метки с наибольшим числом серий
- `match[]=SELECTOR` — фильтр по селектору

`tsdb`-эндпоинт — быстрая первая диагностика high-cardinality метрик; проактивная оценка по живому потоку — в [vmestimator](./vmestimator.md).

### 4. Удаление серий (админ-операция)

```bash
# Удалить все серии с именем temp_metric*
curl -s -X POST 'http://localhost:8428/api/v1/admin/tsdb/delete_series' \
  --data-urlencode 'match[]={__name__=~"temp_metric.*"}'
# → 204 (удаление фоновое, не мгновенное)

# В кластере — через vmselect
curl -s -X POST 'http://vmselect:8481/delete/0/prometheus/api/v1/admin/tsdb/delete_series' \
  --data-urlencode 'match[]={__name__=~"temp_metric.*"}'
```

Операция асинхронная и нагружает IO: применяйте точечно, в окно. Защита auth-ключом `-deleteAuthKey`. С v1.149.0 эндпоинт принимает **только POST** (защита от SSRF-удаления данных). Перед удалением рекомендуется проверить затронутые серии:

```bash
curl -sG 'http://localhost:8428/api/v1/series' \
  --data-urlencode 'match[]={__name__=~"temp_metric.*"}' \
  --data-urlencode 'start=2026-10-01T00:00:00Z' \
  --data-urlencode 'end=2026-10-02T00:00:00Z' | jq '.data | length'
```

Ограничения на удаление:
- `-search.maxDeleteSeries` — максимум серий на один вызов
- `-search.maxDeleteDuration` — максимальная длительность

После удаления дисковое пространство освобождается не мгновенно — данные удаляются при фоновой компакции. Для ускорения можно вызвать `/internal/force_merge`.

### 5. Снапшоты: как бэкап-утилита берёт данные

```bash
# Создать снапшот (мгновенно, без остановки)
curl -s -X POST 'http://localhost:8428/snapshot/create' | jq .
# {"status":"ok","snapshot":"20260922T123456.789"}
ls /var/lib/victoria-metrics/snapshots/

# Список снапшотов
curl -s 'http://localhost:8428/snapshot/list' | jq .

# Удалить конкретный снапшот
curl -s -X POST 'http://localhost:8428/snapshot/delete?snapshot=20260922T123456.789' | jq .
# или через DELETE
curl -s -X DELETE 'http://localhost:8428/snapshot/20260922T123456.789' | jq .

# Удалить все снапшоты
curl -s -X POST 'http://localhost:8428/snapshot/delete_all' | jq .
```

Снапшот — застывшая копия данных; именно по нему работает [vmbackup](./vmbackup_restore.md). Снапшоты создаются через hard-link и symlink на существующие parts и не занимают диск сразу — диск заполняется по мере merge старых parts.

### 6. Интроспекция конфигурации и состояния

```bash
# Все флаги запущенного процесса
curl -s http://localhost:8428/flags | jq .
# или через Prometheus API
curl -s http://localhost:8428/api/v1/status/flags | jq '.data | {retentionPeriod, httpListenAddr}'

# Активные запросы — если vmselect «завис»
curl -s http://vmselect:8481/api/v1/status/active_queries | jq .

# Самые частые и медленные запросы
curl -s 'http://localhost:8428/api/v1/status/top_queries?topN=10&maxLifetime=5m' | jq .

# Версия и buildinfo
curl -s http://localhost:8428/api/v1/status/buildinfo | jq .
# {"status":"success","data":{"version":"victoriametrics/v1.154.0"}}

# Healthcheck
curl -s http://localhost:8428/-/healthy     # → VictoriaMetrics is Healthy.
curl -s http://localhost:8428/-/ready        # → VictoriaMetrics is Ready.
curl -s http://localhost:8428/health         # → {} (non-OK во время shutdown)
```

`/flags` показывает фактические значения всех флагов процесса — первое место при диагностике «почему не так, как я настроил». Доступ можно ограничить флагом `-flagsAuthKey`.

### 7. Приём данных через Prometheus Remote Write (`/api/v1/write`)

```bash
# В конфигурации Prometheus (prometheus.yml)
remote_write:
  - url: http://localhost:8428/api/v1/write

# В кластере — через vminsert с тенантом
remote_write:
  - url: http://vminsert:8480/insert/0/prometheus/api/v1/write
```

Эндпоинт принимает данные в Prometheus Remote Write v1 протоколе (snappy-сжатый Protobuf). VictoriaMetrics также поддерживает OpenTelemetry (OTLP), InfluxDB line protocol, Graphite, OpenTSDB и DataDog протоколы на соответствующих путях — см. [vmagent](./vmagent_overview.md) и [overview](./overview.md).

### 8. Индексация и метаданные

```bash
# Список всех меток
curl -s 'http://localhost:8428/api/v1/labels' | jq '.data'

# Значения метки
curl -s 'http://localhost:8428/api/v1/label/job/values' | jq '.data'

# Метаданные метрик
curl -s 'http://localhost:8428/api/v1/metadata?metric=up' | jq '.data'

# Общее количество серий
curl -s 'http://localhost:8428/api/v1/series/count' | jq '.data'

# Федерация (для вышестоящего Prometheus)
curl -sG 'http://localhost:8428/federate' \
  --data-urlencode 'match[]={job="node_exporter"}' \
  > federated.txt
```

## Валидация установки

```bash
# Healthcheck для всех компонентов
curl -s http://localhost:8428/health            # → {}
curl -s http://vminsert:8480/health             # → {}
curl -s http://vmselect:8481/health             # → {}

# Запись → чтение
curl -s -X POST http://localhost:8428/api/v1/import/prometheus \
  --data-binary 'test_metric{job="manual"} 123'
# → 204 (данные приняты)

curl -s 'http://localhost:8428/api/v1/query?query=test_metric' | jq '.data.result[0].value[1]'
# → "123"
```

## Поиск и устранение неисправностей

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| `405 Method Not Allowed` | Не тот HTTP-метод (import требует POST) | Проверить метод; снапшоты — GET/POST, delete_series — POST |
| «too many labels per series» | Много меток/излишние метки | Пересмотреть relabeling в [vmagent](./vmagent_overview.md); `-maxLabelsPerTimeseries` |
| `204` на импорте, но данных нет | Неверное имя `match[]` или формат данных | Проверить; для отладки сначала `/api/v1/import/prometheus` с одной записью |
| Экспорт пуст | Фильтр `match[]` не совпадает / данные старше `retentionPeriod` | Расширить фильтр, проверить диапазон времени |
| `vmselect` тормозит, длинный `active_queries` | Тяжёлые запросы | `timeout`, `-search.maxQueryDuration`, `-search.maxQueryLen`; посмотреть `/api/v1/status/active_queries` |
| `409 Conflict` на delete_series | Дубликат операции в очереди | Повторить позже; ограничить `-search.maxDeleteSeries` |
| Данные не видны сразу после импорта | In-memory буферы не сброшены | Вызвать `/internal/force_flush` перед запросом |
| High cache miss на vmselect | Мало RAM на кеши | Увеличить `-storage.cacheSize*` или RAM |
| `vm_slow_row_inserts_total` растёт | Недостаточно RAM для активных серий | Увеличить RAM или уменьшить кардинальность через relabeling |

## Рекомендации по эксплуатации

- **Не открывайте `/api/v1/write`, `/insert/*`, `/snapshot/create`, `/api/v1/admin/tsdb/delete_series` в интернет** — только через [vmauth](./vmauth_overview.md) или обратный прокси (см. [security.md](./security.md)). Используйте auth-ключи (`-deleteAuthKey`, `-snapshotAuthKey`, `-reloadAuthKey`, `-flagsAuthKey`, `-configAuthKey`).
- **Для регламентных выгрузок** используйте GET-export с `match[]` и диапазоном; без `match[]` возможен огромный объём.
- **Для больших выгрузок** предпочитайте native-формат и [vmctl](./vmctl_migration.md) — он режет диапазоны на блоки, ретраит и поддерживает `--verify-block`.
- **Native-формат — только между VictoriaMetrics**; не смешивайте с Prometheus-текстом.
- **Снапшоты удаляйте после бэкапа** (через `/snapshot/delete` или `-snapshotsMaxAge`), иначе заполнят диск в `snapshots/`.
- **Операции delete_series/export на больших данных** планируйте в окно — это нагрузка на IO/indexdb.
- **Для удаления исторических данных** используйте `/internal/force_merge?partition_prefix=YYYY_MM` для освобождения диска после `delete_series`.
- **Не меняйте путь `/snapshot/<name>`** через `rm` — используйте API `/snapshot/delete?snapshot=...`.
- **Ограничьте ресурсы** через флаги `-search.maxExportSeries`, `-search.maxDeleteSeries`, `-search.maxQueryDuration`, `-import.maxLineLen` (по умолчанию 10MB для JSON-линий при импорте).
- **Для backfilling** исторических данных отключайте query cache (`-search.disableCache`) или сбрасывайте через `/internal/resetRollupResultCache` после загрузки.

## Ограничения и особые случаи

- **Экспорт — поток линейно по времени**; повторный одинаковый запрос дорог для vmselect. Для больших выгрузок предпочитайте vmctl/native.
- **Чтение в кластере** отдаёт частичный ответ при недоступности части `vmstorage`: в ответе присутствует `"isPartial": true` (см. [cluster_operations](./cluster_operations.md)).
- **Удаление серий не освобождает диск немедленно** — данные удаляются при фоновой компакции (merge). Для исторических партиций merge может не запускаться — используйте `/internal/force_merge`.
- **Снапшоты по умолчанию** лежат в `-storageDataPath/snapshots/` — заложите место под них в capacity-планировании.
- **`/api/v1/status/tsdb` в кластере** может возвращать завышенные значения при репликации или рероутинге, так как vmselect суммирует статистику с каждого vmstorage.
- **CSV импорт** требует обязательного параметра `format`; первая строка файла считается заголовком, но может быть пропущена при нечисловых значениях.
- **JSON-line импорт** загружает каждую строку полностью в память; строки длиннее 10MB отклоняются (`-import.maxLineLen`). Рекомендуется 1K–10K samples на строку.
- **`/api/v1/export` дедуплицирует** данные согласно `-dedup.minScrapeInterval`; `reduce_mem_usage=1` отключает дедупликацию для недавно записанных данных.
- **`/snapshot/create`** создаёт hard-link и symlink на существующие parts — диск не заполняется сразу, но растёт по мере merge старых parts.
- **`/api/v1/admin/tsdb/delete_series` с v1.149.0** принимает только POST (защита от SSRF-атак).

## Дополнительная информация

### См. также

- [VictoriaMetrics: обзор](./overview.md) — порты, флаги, capacity, архитектура кластера;
- [vmctl: миграция данных](./vmctl_migration.md) — native-режим поверх этих API;
- [vmbackup/vmrestore](./vmbackup_restore.md) — бэкап через `/snapshot/create`;
- [vmestimator](./vmestimator.md) — анализ кардинальности перед `/api/v1/status/tsdb`;
- [vmauth: прокси и маршрутизация](./vmauth_overview.md) — защита `/insert/*` и `/select/*`;
- [vmagent: обзор](./vmagent_overview.md) — приём метрик через remote_write;
- [Хранилище метрик: внутреннее устройство](./storage_internals.md) — force_merge, force_flush, структура данных;
- [Безопасность VictoriaMetrics](./security.md) — защита эндпоинтов, TLS, auth-ключи;
- [Prometheus HTTP API](../Prometheus/prometheus_api.md) — API, совместимый с `/api/v1/...` VictoriaMetrics;
- [Документация VictoriaMetrics](https://docs.victoriametrics.com/victoriametrics/url-examples/) — официальные примеры запросов.