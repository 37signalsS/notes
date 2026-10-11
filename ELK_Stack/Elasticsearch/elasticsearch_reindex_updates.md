# Elasticsearch: Reindex, Update и Delete by Query

**Актуально для:** Elasticsearch 9.5.x / 8.19 LTS

> Руководство по массовым операциям над документами: `_reindex` (копирование/пересоздание), `_update_by_query` (обновление по запросу), `_delete_by_query` (удаление по запросу) и точечный `_update`. Рассматриваются задачи (Task API), троттлинг, параллелизация (slices), reindex from remote и типовые production-сценарии.
>
> Связанные темы: выбор документов — [Query DSL](./elasticsearch_query_dsl.md); обработка при записи — [Ingest Pipelines](./elasticsearch_ingest_pipelines.md); смена схемы через reindex + алиас — [Mapping and Indexing](./elasticsearch_mapping_and_indexing.md); миграции версий с reindex — [Upgrades](./elasticsearch_upgrades.md); массовые операции и merge-нагрузка — [Troubleshooting индексации](./elasticsearch_troubleshooting_indexing.md).

## Определения

* **`_reindex`** — копирование документов из источника (`source`: индекс, data stream, алиас, wildcard или remote-кластер) в назначение (`dest`) с возможностью фильтрации `query`, трансформации через `script` и прогона через ingest pipeline (`dest.pipeline`).
* **`_update_by_query`** — применение script/ingest pipeline ко всем документам индекса, удовлетворяющим `query`, без копирования: документы обновляются на месте (инкремент версии, reindex сегментов при обновлении).
* **`_delete_by_query`** — удаление документов по `query`. Механически — reindex с `op_type: delete`.
* **`_update` (Update API)** — точечное обновление одного документа по `_id`: частичный merge `_source` (`doc`) или `script`, апсерт (`upsert`).
* **Task API** — асинхронное выполнение массовых операций: при `wait_for_completion=false` запрос возвращает `task` id, за прогрессом можно следить (`GET _tasks/<id>`), менять троттлинг (`_rethrottle`) и отменять (`_tasks/<id>/_cancel`).
* **Slices** — горизонтальное параллелизирование операции на независимые подзадачи (аналог sliced scroll); `auto` — Elasticsearch выбирает число слайсов сам.
* **Reindex from remote** — копирование с другого Elasticsearch-кластера (включая старые версии — основной путь апгрейда без downtime); требует `reindex.remote.whitelist`.

## Основные концепции

### Что делает каждый API

| API | Что происходит с документом | Типичные use cases |
|---|---|---|
| `_reindex` | Копия в назначении; источник не меняется | Смена маппинга/числа шардов, апгрейд версии, перенос между кластерами, наполнение тестовой выборки |
| `_update_by_query` | Перезапись на месте (version bump) | Обогащение/нормализация поля у существующих документов, исправление значения по шаблону |
| `_delete_by_query` | Удаление | Чистка по критерию (retention, тестовые данные) |
| `_update` | Частичный merge/скрипт одного документа | Точечные правки, апсерт из приложения |

Ключевое следствие: `update_by_query` и `delete_by_query` читают и переписывают документы — это нагрузка на запись (reindex сегментов, merge). После массовых обновлений кластер может замедлиться из-за merge-сторма — сценарий и разбор в [Troubleshooting индексации](./elasticsearch_troubleshooting_indexing.md).

### Предварительные требования

* `_reindex` требует **включённого `_source`** у документов-источника.
* **Назначение настраивается заранее:** reindex не копирует settings и шаблоны — маппинг, число шардов, replicas, lifecycle-политику задайте до запуска (`PUT` назначения или шаблон).
* Привилегии: `read` на источник, `write` (или `create_index`/`auto_configure`) на назначение; для remote — `monitor` на удалённый кластер и запись `reindex.remote.whitelist` в `elasticsearch.yml` (в координирующих узлах).
* `dest` по умолчанию принимает документы с любым `_id` (перезапись совпадающих); `require_alias: true` — запретить автоматическое создание индекса, разрешить только алиас.

### Асинхронный запуск и Task API

```bash
# Запуск в фоне: запрос сразу возвращает task id
POST _reindex?wait_for_completion=false
{ "source": { "index": "logs-2024" }, "dest": { "index": "logs-2024-clean" } }
# → {"task": "node-A:123456"}

# Прогресс
GET _tasks/node-A:123456
# → {"completed": false, "task": {"status": {"created": 50000, "total": 200000}, ...}}

# Остановка
POST _tasks/node-A:123456/_cancel

# Список всех reindex-задач
GET _tasks?actions=*reindex*&detailed=true
```

Ответ завершённой задачи содержит `created`/`updated`/`deleted`/`version_conflicts`/`batches`/`failures`. История задач живёт в системном индексе `.tasks` (нужна для поиска старых задач; при `wait_for_completion=true` задача удаляется по завершении).

### Управление задачами reindex (9.5+: новые API)

Начиная с 9.5, для асинхронных reindex-операций доступен набор выделенных API, которые заменяют вызовы через `/_tasks`. Они работают с переносом задач между узлами:

| Метод | Путь | Назначение |
|---|---|---|
| `GET` | `/_reindex` | Список всех запущенных reindex-задач (перекрывает `GET _tasks?actions=*reindex*`) |
| `GET` | `/_reindex/{task_id}` | Статус конкретной задачи: прогресс, метрики, финальный ответ после завершения |
| `POST` | `/_reindex/{task_id}/_cancel` | Отмена задачи (заменяет `POST _tasks/{node_id:task_id}/_cancel`) |
| `POST` | `/_reindex/{task_id}/_rethrottle?requests_per_second=N` | Изменение троттлинга на лету |

Особенности:

* **Relocation (устойчивость к shutdown):** асинхронная reindex-операция (`wait_for_completion=false`) выживает graceful shutdown узла — задача автоматически переезжает на другой узел и продолжает с последнего завершённого батча без вмешательства. Используйте `GET /_reindex/{task_id}` с оригинальным `task_id` на протяжении всего цикла — ID остаётся стабильным даже после переезда.
* **ID формата:** `task_id` в новых API — строка, назначаемая системой. Устаревший формат `node_id:local_task_id` принимается для обратной совместимости (legacy `/_tasks` endpoints).
* **Привилегии (9.5+, least-privilege):** введены кластерные привилегии:
  * `monitor_reindex` — read-only (list, get status);
  * `manage_reindex` — включает `monitor_reindex` плюс cancel и rethrottle.

```bash
# Список всех reindex-задач (9.5+)
GET _reindex

# Статус конкретной задачи
GET _reindex/r1A2WoRbTwKZ516z6NEs5A:36619
# → {"task_id": "...", "completed": false, "status": {"total": 50000, "created": 12000, ...}}

# Cancel (9.5+)
POST _reindex/r1A2WoRbTwKZ516z6NEs5A:36619/_cancel
# ← {"canceled": true}

# Retrottle (9.5+, заменяет POST _tasks/{task_id}/_rethrottle)
POST _reindex/r1A2WoRbTwKZ516z6NEs5A:36619/_rethrottle?requests_per_second=500
```

### Троттлинг и параллелизация

* `requests_per_second` (**default −1** — без ограничения) — темп выпуска bulk-батчей; ограничение реализуется «подкладыванием ожидания» между батчами (batch size по умолчанию **1000**).
* `_rethrottle` — изменить темп на лету: `POST _reindex/<task_id>/_rethrottle?requests_per_second=500`. Ускорение применяется сразу, замедление — после текущего батча.
* `slices` (`auto` или число) — распараллеливание; каждый слайс — отдельная подзадача со своим снапшотом источника. Ускорение примерно линейно до числа слайсов ≈ number of shards. **Для remote-reindex slicing не поддерживается.**
* `max_docs` ограничивает число обрабатываемых документов; при `conflicts=proceed` фактически обработано может быть больше (поиск продолжается до набора `max_docs` успешных).

### Конфликты версий

`conflicts` (**default `abort`**) — поведение при version conflict (документ изменился во время операции):

* `abort` — операция останавливается, в ответе `version_conflicts` и `failures`;
* `proceed` — конфликтующие документы пропускаются, считаются в `version_conflicts`, операция доводится до конца.

Для массовых операций по «живым» индексам обычно ставят `conflicts=proceed`, затем анализируют конфликты и при необходимости повторяют.

### Конфигурация назначения: version_type и op_type

Элемент `dest` поддерживает параметры оптимистичной конкуренции (OC), аналогичные index API:

| Параметр | Значение | Поведение |
|---|---|---|
| `version_type` | `internal` (default) | Перезапись «вслепую»: документ с совпадающим `_id` перезаписывается без проверки версии |
| `version_type` | `external` | Сохраняет `version` из источника; создаёт документы, которых нет, и обновляет только если `version` в dest строго меньше |
| `version_type` | `external_gte` | Как `external`, но сравнение `>=`; осторожно — при неверном использовании может вызвать потерю данных |
| `op_type` | `index` (default) | Перезапись существующих документов |
| `op_type` | `create` | Только создание новых; существующие вызывают конфликт версии |

Для **data stream** назначения: `op_type` обязан быть `create` — data stream append-only, reindex может только добавлять новые документы, не обновлять существующие.

```bash
# Сохранение версии при миграции между кластерами
POST _reindex
{
  "source": { "index": "orders-7x" },
  "dest": { "index": "orders-9x", "version_type": "external" },
  "script": {
    "source": "ctx._version = ctx._version + 1",
    "lang": "painless"
  }
}
```

### Локальный reindex: PIT вместо scroll (9.5+)

Начиная с 9.5, локальный `_reindex` (и reindex from remote ≥ 7.10) читает источник через **point-in-time**-пагинацию, а не scroll: параметр `scroll` на этом пути игнорируется, время жизни контекста задаётся `cluster.reindex.pit.keep_alive`. В версиях 8.x и 9.0–9.4 используется scroll-based пагинация (параметр `scroll` действует). Remote-источники старше 7.10 не поддерживают PIT и работают по scroll.

Значение `cluster.reindex.pit.keep_alive` по умолчанию **15m** (минимум `1ms`, dynamic setting — меняется через `PUT _cluster/settings` без рестарта). Устанавливайте достаточно для сетевого latency и batching, но не excessive — PIT retainer ресурсы на data-нодах до истечения/закрытия.

В 9.5+ reindex-задачи также **relocation-aware**: при graceful shutdown узла задача переезжает на другой узел (см. [Управление задачами](#управление-задачами-reindex-95-новые-api)) и продолжает с последнего завершённого батча.

## Практические сценарии

### 1. Reindex с трансформацией: нормализация поля

```bash
POST _reindex?wait_for_completion=false&conflicts=proceed
{
  "source": { "index": "orders-v1" },
  "dest":   { "index": "orders-v2" },
  "script": {
    "source": """
      ctx._source.status = ctx._source.status.toLowerCase();
      ctx._source.tags = ['migrated'];
      if (ctx._source.priority == null) { ctx._source.priority = 'normal'; }
    """
  }
}
# → {"task": "..."}
```

`script` выполняется на стороне источника, до записи в назначение; `ctx._id`, `ctx._index` доступны (смена `_index` в скрипте — способ распределить документы по нескольким назначениям). Painless-скрипты компилируются и кэшируются; rate-limit — `script.max_compilations_rate` (75/5m).

### 2. Reindex + ingest pipeline (обогащение на лету)

```bash
POST _reindex
{
  "source": { "index": "raw-events" },
  "dest":   { "index": "enriched-events", "pipeline": "geo-parse" }
}
```

`dest.pipeline` — прогнать каждый скопированный документ через пайплайн (geoip, user_agent, convert и др. — [Ingest Pipelines](./elasticsearch_ingest_pipelines.md)). Альтернатива `script`, когда обработка уже описана процессорами.

### 3. Смена схемы без простоя: reindex + атомарное переключение алиаса

```bash
# 1. Создать новое имя/индекс с целевым маппингом (settings/mappings заданы заранее)
PUT orders-v2

# 2. Копировать данные
POST _reindex?wait_for_completion=false
{ "source": { "index": "orders-v1" }, "dest": { "index": "orders-v2" } }

# 3. После завершения задачи — атомарно переключить алиас
POST _aliases
{ "actions": [
    { "remove": { "index": "orders-v1", "alias": "orders" } },
    { "add":    { "index": "orders-v2", "alias": "orders" } }
] }

# 4. Убедиться, что данные на месте, и удалить старый индекс
GET orders/_count
DELETE orders-v1
```

Тот же паттерн используется в сценарии «Миграция маппинга без простоя» ([Mapping and Indexing](./elasticsearch_mapping_and_indexing.md)) и в Blue-Green обновлениях ([Upgrades](./elasticsearch_upgrades.md)). Пока копирование идёт, обе стороны продолжают работать; переключение алиаса — единственная операция, которую видят клиенты.

### 4. Update by query: массовое исправление значения

```bash
POST logs-*/_update_by_query?conflicts=proceed&refresh=true
{
  "query": { "term": { "host.name": "old-node-01" } },
  "script": { "source": "ctx._source.host.name = 'new-node-01'" }
}
# → {"total": 152000, "updated": 152000, "version_conflicts": 3, "failures": []}
```

* `refresh=true` — сделать результат видимым для поиска сразу (для отладки; в проде чаще оставляют по умолчанию).
* Обновление по data stream: `POST <data-stream>/_update_by_query` — поддерживают и `_update_by_query`, и `_delete_by_query` (сам `_update` по `_id` — нет, data stream append-only; первая запись с `_id` выигрывает).
* Отключить default ingest pipeline для конкретного запроса: `?pipeline=_none` (`final_pipeline` выполнится в любом случае).

### 5. Delete by query: выборочная чистка

```bash
POST metrics-*/_delete_by_query?conflicts=proceed&scroll_size=5000
{
  "query": { "range": { "@timestamp": { "lt": "now-90d" } } }
}
# → {"deleted": 980000, "batches": 980, "version_conflicts": 12, "noops": 0}
```

`scroll_size` (default 1000) — размер батча чтения; для удаления больших объёмов его поднимают, чтобы снизить накладные на scroll/PIT-контексты. Альтернатива массовому delete-by-query по времени — [ILM](./elasticsearch_ilm_and_retention.md) (удаление целых индексов дешевле, чем пофайловое удаление документов).

### 6. Reindex from remote: апгрейд со старого кластера

```bash
# elasticsearch.yml координирующего узла (static, требуется restart)
# reindex.remote.whitelist: "old-es.example.com:9200"

POST _reindex?wait_for_completion=false
{
  "source": {
    "remote": {
      "host": "http://old-es.example.com:9200",
      "username": "reindex_user",
      "password": "****"
    },
    "index": "orders",
    "query": { "match_all": {} }
  },
  "dest": { "index": "orders", "pipeline": "legacy-normalize" }
}
```

Особенности:

* Работает с Elasticsearch **любой версии на источнике** (в том числе до 7.10 — основной путь апгрейда 6.x/7.x → 9.x без кластерного простоя); обратная совместимость вниз не поддерживается (из 7.x в 6.x нельзя).
* `query` на remote передаётся без валидации — только для совместимости со старыми версиями.
* Slicing не поддерживается; буфер чтения on-heap, default 100 МБ (`batch_size` уменьшается для крупных документов).
* При remote ≥ 7.10 (и стеке 9.5+) чтение идёт через PIT на удалённой стороне.
* **SSL настройки** (в `elasticsearch.yml`, static, требуется restart на всех узлах): `reindex.ssl.certificate_authorities` (путь к PEM CA bundle), `reindex.ssl.verification_mode` (`full`/`certificate`/`none`, default `full`). Для self-signed сертификатов — добавить CA и/или `verification_mode: certificate`. Настройки SSL нельзя задать в теле запроса.

```bash
# elasticsearch.yml (пример для self-signed CA)
# reindex.remote.whitelist: ["old-es.example.com:9200"]
# reindex.ssl.certificate_authorities: "/etc/elasticsearch/certs/source-ca.pem"
# reindex.ssl.verification_mode: "certificate"
```

### 7. Выборочная загрузка и контроль объёма

```bash
# Случайная выборка для тестов
POST _reindex
{
  "max_docs": 1000,
  "source": { "index": "orders",
              "query": { "function_score": { "random_score": {}, "min_score": 0.9 } } },
  "dest":   { "index": "orders-sample" }
}

# Троттлинг на проде, чтобы не перегружать кластер
POST _reindex?requests_per_second=2000&conflicts=proceed
{ "source": { "index": "hot-index" }, "dest": { "index": "warm-index" } }
```

### 8. Reindex в data stream (op_type: create)

```bash
POST _reindex?wait_for_completion=false
{
  "source": { "index": "logs-archive-2024" },
  "dest": {
    "index": "logs-stream",
    "op_type": "create"
  }
}
# → {"task": "..."}
```

* **Data stream append-only:** `op_type` обязан быть `create` — иначе `illegal_argument_exception`. Существующие документы с теми же `_id` не перезаписываются, а вызывают конфликт версии (первая запись с `_id` выигрывает).
* Для автоматического создания data stream — в destination нужен index template с `"data_stream": {}` (см. [Mapping and Indexing](./elasticsearch_mapping_and_indexing.md)); `require_alias: true` допускает только существующие алиасы.
* Миграция с сохранением версии: добавьте `"version_type": "external"` в `dest` (полезно для cross-cluster сокращения).

## Troubleshooting

| Ошибка / симптом | Причина | Решение |
|---|---|---|
| `reindex.remote.whitelist ... not set` | Remote-хост не разрешён | Добавить хост в `reindex.remote.whitelist` (static, на всех координирующих узлах) |
| `cannot reindex if _source is disabled` | У источника выключен `_source` | Включить `_source` (или восстанавливать из stored fields невозможно — только экспорт до отключения) |
| `Failures` c `version_conflicts` | Документ изменился во время операции | `conflicts=proceed` + повторный прогон; для update — реже, т.к. конфликты самолечатся повтором |
| Задача «висит», `completed: false` долго | Большой объём, нет троттлинга/мало слайсов | `requests_per_second` для ограничения нагрузки, `slices` для параллелизма, следить через `GET _tasks` |
| После `update_by_query` кластер замедлился | Массовый reindex сегментов → merge-сторм | Сценарий и разбор — [Troubleshooting индексации](./elasticsearch_troubleshooting_indexing.md); `indices.indexing.throttle` при экстремальных объёмах |
| Назначение создалось с дефолтным маппингом | Reindex не копирует settings/mappings | Создавать назначение (или шаблон) заранее; после — проверить `GET <dest>/_mapping` |
| `searchParseException` / невалидный query на remote | Query не проходит валидацию старой версии | Упростить запрос, фильтровать на стороне-назначении после копирования |
| `_delete_by_query` удалило не всё | Обновления во время сканирования + `abort` | `conflicts=proceed`; повторный прогон добьёт остатки |
| Дубликаты при повторном reindex | Совпадающие `_id` перезаписываются (это не дубли), либо источник указывал на назначение | Источник и назначение не должны пересекаться по wildcard; идемпотентность — по `_id` |
| Reindex в data stream без `op_type: create` | `illegal_argument_exception`: data stream требует `op_type=create` | Добавить `"op_type": "create"` в `dest` |
| Remote reindex: SSL certificate error | Self-signed или просроченный CA не доверяется | Добавить `reindex.ssl.certificate_authorities` и `reindex.ssl.verification_mode: certificate` в `elasticsearch.yml` на всех узлах; перезапустить |
| `reindex.ssl.verification_mode` игнорируется | Настройка not static или не на всех узлах | `reindex.ssl.*` — static (только в `elasticsearch.yml`), требует restart; на всех координирующих узлах |
| Node shutdown прерывает reindex | ES 8.x: задача теряется при `wait_for_completion=true`; в 9.5+ выживает relocation | В 9.5+ используйте `GET /_reindex/{task_id}` для отслеживания после переезда; в 8.x — планировать на окна без shutdown

## Best Practices

* **Настраивайте назначение заранее** (mappings, settings, шаблоны, ILM) — reindex ничего этого не переносит.
* **В проде — `wait_for_completion=false` + Task API:** наблюдаемость, возможность `_rethrottle` и `_cancel`, отсутствие таймаута на стороне HTTP-клиента. В 9.5+ используйте выделенные API (`/_reindex`, `/_reindex/{id}/_cancel`, `/_reindex/{id}/_rethrottle`) — они relocation-aware.
* **`conflicts=proceed`** для массовых операций по живым индексам; итоговые `version_conflicts` проверяйте и при необходимости повторяйте прогон.
* **Троттлите** большие операции (`requests_per_second`) в рабочие часы; глубокие — ночью без ограничений.
* **`slices: auto`** для локальных reindex/delete по многим шардам; slicing для remote недоступен.
* **Не запускайте параллельно** много тяжёлых reindex — они конкурируют за write/merge ресурсы; очередность через Task API или `GET /_reindex`.
* **Считайте ROI `update_by_query` против reindex в новый индекс:** обновление на месте переписывает сегменты; при очень больших изменениях часто дешевле пересоздать индекс и переключить алиас.
* **Для чистки по времени** предпочитайте ILM/DSL-удаление индексов, а не `_delete_by_query` по каждому документу.
* **Reindex в data stream:** обязательно `op_type: create` + index template с `"data_stream": {}`; для cross-cluster миграций добавляйте `version_type: external`.
* **После массовых операций** проверьте `_cat/segments`, размер сегментов и состояние health; при merge-сторме — разбор в [Troubleshooting индексации](./elasticsearch_troubleshooting_indexing.md). Использование `version_type: external`/`external_gte` требует осторожности — ошибка может привести к потере данных.

## См. также

* **[Query DSL](./elasticsearch_query_dsl.md)** — `query` в `source`, `must`/`filter` для отбора документов.
* **[Mapping and Indexing](./elasticsearch_mapping_and_indexing.md)** — смена схемы через reindex + алиас, bulk API, транслированные ограничения; сценарий «Миграция маппинга без простоя».
* **[Ingest Pipelines](./elasticsearch_ingest_pipelines.md)** — `dest.pipeline`, процессоры обогащения.
* **[Upgrades](./elasticsearch_upgrades.md)** — Blue-Green с reindex, апгрейд-чеклист с reindex старых индексов; `_migration/reindex` API для upgrade backing indices data stream.
* **[Disaster Recovery](./elasticsearch_disaster_recovery.md)** — `_reindex` from remote как обход несовместимости версий при restore.
* **[Troubleshooting индексации](./elasticsearch_troubleshooting_indexing.md)** — merge-сторм после массовых обновлений, метрики записи.
* **[ILM и политики хранения](./elasticsearch_ilm_and_retention.md)** — ретеншн через удаление индексов вместо delete_by_query.

### Перекрытие с существующими файлами (§0.10)

* `Elasticsearch/elasticsearch_mapping_and_indexing.md` — SSoT по смене маппинга (сценарий «Миграция маппинга без простоя») и bulk API; настоящий файл даёт полный разбор самих API массовых операций, случай с алиасом только резюмирует со ссылкой.
* `Elasticsearch/elasticsearch_upgrades.md` — SSoT по апгрейдам (Blue-Green, Upgrade Assistant); reindex здесь описан как механизм, применение в апгрейдах — там.
* `Elasticsearch/elasticsearch_troubleshooting_indexing.md` — SSoT по последствиям массовых обновлений (merge-сторм, метрики); здесь лишь ссылка.
* `Elasticsearch/elasticsearch_disaster_recovery.md` — reindex from remote упоминается как обход несовместимости версий при restore; детали remote-конфигурации — в настоящем файле.
* `Elasticsearch/elasticsearch_ingest_pipelines.md` — SSoT по процессорам и `dest.pipeline`; настоящий файл использует pipeline как параметр `dest`.
