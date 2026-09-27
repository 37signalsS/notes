# VictoriaMetrics: справочник HTTP API и практика

## Определения

**HTTP API VictoriaMetrics** — набор endpooint-ов на `httpListenAddr` для записи, чтения, администрирования и диагностики. Для single-node всё висит на одном порту (по умолчанию `8428`); в кластере запись идёт в `vminsert` (`8480`), чтение — в `vmselect` (`8481`), служебные эндпоинты — в `vmstorage` (`8482`).

**Префиксы кластера** — `/insert/<accountID>/<projectID>/prometheus/...` (запись) и `/select/<accountID>/<projectID>/prometheus/...` (чтение). В single-node тенант не указывается.

**Native-протокол** (`/api/v1/export/native`, `/api/v1/import/native`) — бинарный формат VictoriaMetrics для переноса данных между своими инстансами без перекодировки (используется в [vmctl](./vmctl_migration.md)). Самый быстрый способ миграции.

## Базовые концепции

### Группы эндпоинтов

| Группа | Примеры | Назначение |
| :--- | :--- | :--- |
| Чтение | `/api/v1/query`, `/api/v1/query_range`, `/api/v1/series`, `/api/v1/labels`, `/api/v1/label/<name>/values` | Запросы, метаданные серий |
| Диагностика | `/api/v1/status/tsdb`, `/api/v1/status/active_queries`, `/api/v1/status/buildinfo` | Кардинальность, активные запросы, версия |
| Экспорт/импорт | `/api/v1/export`, `/api/v1/export/native`, `/api/v1/import`, `/api/v1/import/native`, `/api/v1/import/prometheus`, `/api/v1/import/csv` | Выгрузка и загрузка данных |
| Управление данными | `/api/v1/admin/tsdb/delete_series`, `/snapshot/create`, `/snapshot/list`, `/snapshot/delete` | Удаление серий, снапшоты |
| Приём (`remote write`) | `/api/v1/write` (vminsert / single) | Prometheus Remote Write |
| Служебное | `/health`, `/metrics`, `/flags`, `/vmui` | Healthcheck, экспорт метрик, UI |

> В single-node export/import работают на `/api/v1/...`, в кластере — под префиксом тенанта: `/select/<ns>/<pid>/prometheus/api/v1/export` и `/insert/<ns>/<pid>/prometheus/api/v1/import`.

### Форматы экспорта/импорта

- `/api/v1/export` — текстовый экспорт записей в формате JSON-lines (по умолчанию) или Prometheus-текста (`format=prometheus`). Подходит для выгрузки «для глаз», пайплайнов и миграции через сторонние утилиты.
- `/api/v1/export/native` + `/api/v1/import/native` — бинарный протокол: быстрый и плотный, используется vmctl. **Не** является публичным форматом — только VM↔VM.
- `/api/v1/import/prometheus` — загрузка текста Prometheus exposition (например, сохранённого scrape).
- `/api/v1/import/csv` — загрузка CSV с указанием порядка колонок (`metric;timestamp;value`).

### Почему это важно знать на практике

Горячие сценарии эксплуатации (`[vmbackup/vmrestore](./vmbackup_restore.md)`, [vmctl](./vmctl_migration.md), [vmestimator](./vmestimator.md)) построены поверх этих эндпоинтов: снапшоты — это `/snapshot/create`, оценка кардинальности — `/api/v1/status/tsdb`, миграция — native-export. Понимание HTTP API позволяет делать перенос/выгрузку/чистку вручную, не запуская дополнительные утилиты.

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

Ошибок нет — VM отдаёт 200 и потоки JSON-строк, по одной на точку данных. Размер файла может быть большим: сузьте `match[]` и диапазон.

### 2. Экспорт/импорт в native-формате (быстрая миграция вручную)

```bash
# Выгрузка native
curl -sG 'http://localhost:8428/api/v1/export/native' \
  --data-urlencode 'match[]={__name__=~"app_.*"}' \
  --data-urlencode 'start=...' --data-urlencode 'end=...' \
  -o data.native

# Загрузка на целевой инстанс (single-node)
curl -s http://localhost:8429/api/v1/import/native --data-binary @data.native

# В кластере — загрузка через vminsert с тенантом
curl -s http://vminsert:8480/insert/0/prometheus/api/v1/import/native --data-binary @data.native
```

Native-импорт быстрее JSON-lines в разы и не требует переиндексации на приёме. Для больших объёмов используйте [vmctl](./vmctl_migration.md) — он режет диапазоны на блоки и ретраит.

### 3. Кардинальность через `/api/v1/status/tsdb`

```bash
# Топ серий с самыми большими значениями меток (v1.50+)
curl -s 'http://localhost:8428/api/v1/status/tsdb' | jq '.data.labelValueCounters[] | select(.labelName=="instance")' 
# → список (value, count) — самые «раздувающие» значения метки

# серии явным фильтром
curl -sG 'http://localhost:8428/api/v1/series' \
  --data-urlencode 'match[]={job="api"}' | jq '.data | length'
```

`tsdb`-эндпоинт — быстрая первая диагностика high-cardinality метрик. Подробный расчёт ёмкости — в [vmestimator](./vmestimator.md).

### 4. Удаление серий (админ-операция)

```bash
curl -s -X POST 'http://localhost:8428/api/v1/admin/tsdb/delete_series' \
  --data-urlencode 'match[]={__name__=~"temp_metric.*"}'
# → 204 (удаление фоновое, не мгновенное)
```

Операция асинхронная и load-generating: применяйте точечно, в окно. В кластере — через vmselect `/select/<tenant>/prometheus/api/v1/admin/tsdb/delete_series`.

### 5. Снапшоты: как бэкап-утилита берёт данные

```bash
# Создать снапшот (мгновенно, без остановки)
curl -s http://localhost:8428/snapshot/create | jq .
# {"status":"ok","snapshot":"20260922T123456.789"}
ls /var/lib/victoria-metrics/snapshots/

# Список и удаление
curl -s http://localhost:8428/snapshot/list | jq .
curl -s -XDELETE http://localhost:8428/snapshot/20260922T123456.789 | jq .
```

Снапшот — застывшая копия данных; именно по нему работает [vmbackup](./vmbackup_restore.md).

### 6. Интроспекция конфигурации и состояния

```bash
# Все флаги запущенного процесса (как посмотреть фактический конфиг)
curl -s http://localhost:8428/flags | grep remoteWrite

# Активные запросы — если vmselect «завис»
curl -s http://vmselect:8481/api/v1/status/active_queries | jq .

# Версия и buildinfo
curl -s http://localhost:8428/api/v1/status/buildinfo | jq .
```

`/flags` показывает фактические значения всех флагов процесса — первое место при диагностике «почему не так, как я настроил».

## Валидация установки

```bash
curl -s http://localhost:8428/health            # 200 OK
curl -s http://vminsert:8480/health
curl -s http://vmselect:8481/health

# Запись → чтение
curl -s -XPOST http://localhost:8428/api/v1/export/native... >/dev/null   # есть данные
curl -s 'http://localhost:8428/api/v1/query?query=count(up)' | jq '.data.result[0].value[1]'
```

## Поиск и устранение неисправностей

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| `405 Method Not Allowed` | Не тот HTTP-метод (import требует POST) | Проверить метод; снапшоты — GET/POST, delete_series — POST |
| «too many labels per series» | Много меток/излишние метки | Расширить дедуп/ relabeling в [vmagent](./vmagent_overview.md) |
| `204` на импорте, но данных нет | Неверное имя `match[]` `/api/v1/import` vs параметр метрики | Проверить; для отладки сначала `/api/v1/import/prometheus` с одной записью |
| Экспорт пуст | Фильтр `match[]` не совпадает / начали позже `retentionPeriod` | Расширить фильтр, проверить диапазон времени |
| `vmselect` тормозит, длинный `active_queries` | Тяжёлые запросы/мало кеша | `-search.maxQueryDuration`, `deny_partial_response`, посмотреть `/api/v1/status/active_queries` |
| `409 Conflict` на delete_series | Дубликат операции в очереди | Повторить позже |

## Рекомендации по эксплуатации

- Не открывайте `/api/v1/write`, `/insert/*`, `/snapshot/create` в интернет — только через [vmauth](./vmauth_overview.md)/прокси (см. [security.md](./security.md)).
- Для регламентных выгрузок используйте GET-export с `match[]` и диапазоном; без `match[]` возможен огромный объём.
- Native-формат — только между VictoriaMetrics; не смешивайте с Prometheus-текстом.
- Снапшоты удаляйте после бэкапа, иначе заполнят диск в `snapshots/`.
- При операциях delete_series/export на больших данных планируйте окно — это нагрузка на IO/indexdb.

## Ограничения и особые случаи

- Экспорт — поток линейно по времени; повторный одинаковый запрос дорог для vmselect. Для больших выгрузок предпочитайте vmctl/native.
- Чтение в кластере отдаёт частичный ответ при недоступности части `vmstorage`: в ответе присутствует `"isPartial": true` (см. [cluster_operations](./cluster_operations.md)).
- Удаление серий не освобождает диск немедленно — данные будут удалены по мере merge/ротации партиций.
- Снапшоты по умолчанию лежат в `-storageDataPath/snapshots/` — заложите место под них в capacity-планировании.

## Дополнительная информация

### См. также

- [VictoriaMetrics: обзор](./overview.md) — порты, флаги, capacity;
- [vmctl: миграция данных](./vmctl_migration.md) — native-режим поверх этих API;
- [vmbackup/vmrestore](./vmbackup_restore.md) — бэкап через `/snapshot/create`;
- [vmestimator](./vmestimator.md) — анализ кардинальности перед `/api/v1/status/tsdb`;
- [vmauth: прокси и маршрутизация](./vmauth_overview.md) — защита `/insert/*` и `/select/*`;
- [Prometheus HTTP API](../Prometheus/prometheus_api.md) — набор Prometheus, совместимый с `/api/v1/...` VictoriaMetrics.