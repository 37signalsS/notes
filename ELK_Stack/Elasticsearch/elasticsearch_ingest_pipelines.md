# Ingest Pipelines: Обработка документов перед индексацией

**Актуально для:** Elasticsearch 8.x / 9.x

> Систематическое руководство по Ingest Node и пайплайнам обработки документов в Elasticsearch. Рассматриваются процессоры, обработка ошибок, failure store, тестирование и выбор между Ingest Node, Logstash и внешними обработчиками.
>
> Связанные темы: парсинг в Logstash — [Logstash Pipelines](../Logstash/logstash_pipelines.md); маппинг и индексация — [Mapping and Indexing](./elasticsearch_mapping_and_indexing.md); ILM — [ILM и политики хранения](./elasticsearch_ilm_and_retention.md); шаблоны и Data Streams — [Index Templates](./elasticsearch_index_templates.md); [Grok и Dissect Patterns](../grok_dissect_patterns.md); [ELK стек: Обзор](../elk_stack_overview.md).

## Определения

* **Ingest Node** — узел с ролью `ingest` (по умолчанию включена на всех узлах), который перехватывает index и bulk запросы и выполняет предварительную обработку документов через pipelines перед индексацией.
* **Pipeline** — последовательность процессоров (`processors`), применяемых к документу. Определяется через API `PUT _ingest/pipeline/<id>`, хранится в cluster state и доступна на всех узлах кластера.
* **Processor** — единица обработки, выполняющая одно действие над документом (парсинг, обогащение, преобразование полей). Процессоры выполняются последовательно в порядке описания; каждый зависит от выхода предыдущего.
* **Ingest metadata** — служебные поля в пространстве `_ingest` (`_ingest.timestamp`, `_ingest.pipeline`, `_ingest.on_failure_message` и др.). По умолчанию не индексируются.
* **Failure store** — набор вторичных индексов внутри data stream, предназначенный для хранения документов, не прошедших обработку (современный DLQ для Data Streams).
* **Ingest Attachment** — плагин `ingest-attachment` для индексации содержимого файлов (PDF, DOCX) через Apache Tika.
* **Simulate API** — эндпоинт `_ingest/pipeline/_simulate` для тестирования пайплайнов без реальной записи.

## Предварительные требования

* Работающий кластер Elasticsearch 8.x/9.x и доступ к REST API (curl, Kibana Dev Tools, клиент).
* Привилегия `manage_pipeline` для создания и изменения пайплайнов; `read_pipeline`/`manage_ingest_pipelines` или `manage` для чтения и симуляции. Для Kibana Ingest Pipelines также требуется `cluster:monitor/nodes/info`.
* Для выделенных ingest-узлов: `node.roles: [ ingest ]` в `elasticsearch.yml`. Роль `ingest` включена по умолчанию на всех узлах; при тяжёлой нагрузке ingest выносят на отдельные узлы, отключая роль на master- и data-узлах (`node.ingest: false`).
* Плагинные процессоры (например, `ingest-attachment`) должны быть установлены на **всех** узлах кластера, иначе создание пайплайна с таким процессором завершится ошибкой. Обязательность плагина задаётся через `plugin.mandatory: ingest-attachment`.
* Для enrich-процессора — предварительно созданная и выполненная enrich policy (см. раздел «Обогащение»).

## Как работает Ingest

```
Клиент/Beats → [HTTP API] → [Ingest Node: pipeline процессоры] → [Data Node] → Индексация
```

Ingest Node перехватывает index и bulk запросы, применяет указанный пайплайн (или `default_pipeline`/`final_pipeline` индекса), затем передаёт обработанные документы на data node. Обработка выполняется на **write thread pool** (fixed, размер = число процессоров узла; queue_size 10000 в 8.x–9.1, в более новых версиях `max(10000, processors × 750)`) — отдельного ingest thread pool в современных версиях нет.

Процессоры имеют доступ на чтение и запись к `_source` документа. Доступ к полям — по dot-notation (`ctx.user.name`). Документы с flattened-полями (полями с точками в имени) нужно сначала раскрыть через `dot_expander`: в классическом режиме доступа другие процессоры не видят такие поля. Гибкий режим доступа (flexible access pattern) работает и с вложенными, и с точечными именами без `dot_expander`.

Mustache-шаблоны в значениях процессоров: `{{field}}` — поле документа, `{{{_routing}}}` (тройные скобки) — метаданные документа.

### Назначение пайплайна

```bash
# Глобальный для индекса: default_pipeline (при отсутствии параметра запроса) и
# final_pipeline (выполняется после request/default pipeline, даже если они не указаны)
PUT /my-index
{
  "settings": {
    "default_pipeline": "my-pipeline",
    "final_pipeline": "my-final-pipeline"
  }
}

# Через параметр запроса
POST /my-index/_doc?pipeline=my-pipeline
{ "message": "..." }

# В Bulk API
POST /_bulk?pipeline=my-pipeline
{ "index": { "_index": "my-index" } }
{ "message": "..." }

# В _reindex
POST /_reindex
{
  "source": { "index": "my-data-stream" },
  "dest": { "index": "my-new-data-stream", "op_type": "create", "pipeline": "my-pipeline" }
}

# В Beats (filebeat.yml)
output.elasticsearch:
  hosts: ["localhost:9200"]
  pipeline: my-pipeline
```

Fleet и интеграции Elastic Agent применяют свои пайплайны через index templates с настройкой `pipeline` в settings; шаблоны сопоставляются с data streams по схеме именования. **Не изменяйте** пайплайны Fleet-интеграций.

## Управление пайплайнами

```bash
# Создать или обновить (полное перезаписывание определения)
PUT _ingest/pipeline/my-pipeline
{
  "description": "Optional description",
  "version": 1,
  "_meta": { "owner": "sre-team" },
  "processors": [ ... ]
}

# Получить один или все пайплайны (wildcard поддерживается)
GET _ingest/pipeline/my-pipeline
GET _ingest/pipeline

# Удалить
DELETE _ingest/pipeline/my-pipeline

# Список доступных процессоров на узлах
GET _nodes/ingest?filter_path=nodes.*.ingest.processors
```

* **Версионирование:** необязательное целочисленное поле `version` используется с параметром `if_version` для оптимистичной конкуренции при обновлении; при успешном обновлении с `if_version` версия инкрементируется. Поле `_meta` — произвольные метаданные для внешних систем.
* **`deprecated: true`** помечает пайплайн как deprecated; при использовании помеченного пайплайна как `default_pipeline`/`final_pipeline` в непомеченном index template ES выдаёт deprecation warning.
* Обновление пайплайна **не ретроспективно**: уже проиндексированные документы не меняются, новые документы обрабатываются обновлённым пайплайном сразу (пайплайны хранятся в cluster state).
* Удаление пайплайна, на который ссылается `default_pipeline` индекса, приведёт к ошибкам при индексации в этот индекс до тех пор, пока настройка не будет изменена.

## Процессоры

Elasticsearch включает более 40 процессоров. Полный актуальный список — `GET _nodes/ingest?filter_path=nodes.*.ingest.processors`.

### Каталог по категориям

| Категория | Процессоры |
|-----------|------------|
| Обогащение | `append`, `date_index_name`, `enrich`, `attachment` (плагин), `circle`, `community_id`, `fingerprint`, `geo_grid`, `geoip`, `ip_location`, `network_direction`, `normalize_for_stream` (preview 9.1), `registered_domain`, `set_security_user`, `uri_parts`, `urldecode`, `user_agent` |
| Трансформация | `convert`, `dissect`, `grok`, `gsub`, `redact`, `rename`, `set`, `bytes`, `cef`, `csv`, `date`, `dot_expander`, `html_strip`, `join`, `kv`, `lowercase`/`uppercase`, `recover_failure_document`, `split`, `trim` |
| Фильтрация | `drop`, `remove` |
| Управление пайплайном | `fail`, `pipeline`, `reroute`, `terminate` |
| Массивы/JSON | `for_each`, `json`, `script`, `sort` |

Каждый процессор поддерживает общие параметры: `description`, `if` (условие выполнения), `ignore_failure`, `on_failure`, `tag` (идентификатор для отладки и метрик).

### Парсинг и разбор

| Процессор | Назначение | Ключевые параметры |
|-----------|------------|--------------------|
| `grok` | Структурирование строк регулярными выражениями с переиспользуемыми паттернами | `field`, `patterns` (массив, пробуются по порядку), `pattern_definitions` (переопределяют встроенные), `ecs_compatibility` (`disabled`/`v1`, deprecated с 9.4), `ignore_missing`, `validate_only` |
| `dissect` | Разбиение строки по шаблону с разделителями; не использует регулярные выражения — проще и быстрее grok | `field`, `pattern`, `ignore_missing` |
| `csv` | Извлечение строки CSV в поля | `field`, `target_fields`, `separator` |
| `json` | Парсинг JSON-строки в структурированный объект | `field`, `target_field`, `ignore_missing` |
| `kv` | Парсинг пар `key=value` | `field`, `field_split`, `value_split`, `target_field` |
| `gsub` | Замена по регулярному выражению | `field`, `pattern`, `replacement`, `ignore_missing` |
| `uri_parts` | Разбор URI на компоненты | `field`, `target_field` |
| `urldecode` | URL-декодирование строки | `field`, `target_field` |
| `cef` | Извлечение полей из сообщений Common Event Format | `field` |
| `html_strip` | Удаление HTML-тегов из поля | `field`, `target_field` |

Встроенные grok-паттерны можно посмотреть через `GET _ingest/processor/grok` (параметр `s` сортирует по имени). Для отладки grok включается логирование:

```bash
PUT _cluster/settings
{
  "persistent": {
    "logger.org.elasticsearch.ingest.common.GrokProcessor": "debug"
  }
}
```

Grok watchdog прерывает выражения, выполняющиеся слишком долго (тот же watchdog действует и для `redact`).

### Преобразование полей

```json
{
  "set": {
    "field": "status",
    "value": "{{level}}",
    "override": true,
    "ignore_empty_value": false
  },
  "copy": {
    "from": "message",
    "to": "original_message"
  },
  "rename": {
    "field": "old_field",
    "target_field": "new_field",
    "ignore_missing": false
  },
  "remove": {
    "field": ["temp_field", "debug_info"]
  },
  "append": {
    "field": "tags",
    "value": "parsed",
    "allow_duplicates": true
  },
  "lowercase": { "field": "hostname" },
  "uppercase": { "field": "country" },
  "trim": { "field": "message" }
}
```

**Set** — ключевые параметры: `field` (обязательный), `value` или `copy_from` (только одно из двух; `copy_from` копирует сложные значения — массивы, объекты), `override` (по умолчанию `true`; при `false` существующие non-null поля не трогаются), `ignore_empty_value` (тихий выход, если шаблон eval'ится в null/пустую строку), `media_type` (кодирование `value`-шаблона, по умолчанию `application_json`). Доступ к элементам массива — по индексу: `{{{input_field.1}}}`.

**Convert** — приведение типа. Типы (регистр не важен): `integer`, `long`, `float`, `double`, `string`, `boolean`, `ip`, `auto`. Если значение — массив, конвертируются все элементы. `auto` приводит строку к ближайшему нестроковому типу (`"true"` → boolean, `"123"` → integer, `"1.5"` → float); неконвертируемые значения остаются как есть.

```json
{
  "convert": { "field": "status", "type": "integer", "ignore_failure": true },
  "bytes": { "field": "response_size", "target_field": "bytes" },
  "dot_expander": { "field": "foo.bar", "override": false },
  "split": { "field": "tags_csv", "separator": "," },
  "join": { "field": "tags", "separator": "," },
  "sort": { "field": "values", "order": "asc" }
}
```

**Dot expander** — раскрывает поле с точками в объект: `{"foo.bar": "value"}` → `{"foo": {"bar": "value"}}`. При конфликте с существующим вложенным полем значения по умолчанию объединяются в массив; `override: true` — раскрытое значение перезаписывает вложенное. Параметры: `field`, `path`, `override` (по умолчанию `false`).

### Работа с датами

| Параметр | Обязательный | По умолчанию | Описание |
|----------|--------------|--------------|----------|
| `field` | да | — | Поле с датой |
| `target_field` | нет | `@timestamp` | Поле для результата |
| `formats` | да | — | Массив форматов: Java DateTimeFormatter-паттерн или `ISO8601`, `UNIX`, `UNIX_MS`, `TAI64N` |
| `timezone` | нет | `UTC` | Таймзона; поддерживает шаблоны |
| `locale` | нет | `ENGLISH` | Локаль для названий месяцев/дней недели |
| `output_format` | нет | `yyyy-MM-dd'T'HH:mm:ss.SSSXXX` | Формат записи в `target_field` |

```json
{
  "date": {
    "field": "timestamp",
    "target_field": "@timestamp",
    "formats": ["ISO8601", "dd/MMM/yyyy:HH:mm:ss Z"],
    "timezone": "Europe/Moscow",
    "locale": "en"
  }
}
```

Форматы пробуются последовательно в порядке описания. `timezone` влияет двояко: для локальных date-time (без смещения) время считается в указанной таймзоне; для zoned date-time и абсолютных форматов (эпоха) используется время из строки. Избегайте коротких аббревиатур таймзон (`PST`, `CET`, `JST`) — они неоднозначны. `timezone` и `locale` — templated-параметры: `"timezone": "{{{my_timezone}}}"` берёт значение из поля документа.

**date_index_name** — указывает документу time-based индекс на основе поля даты (для индексов без data streams).

Семантика `@timestamp` / `event.created` / `event.ingested`, запоздавшие события и дрейф часов — в [Логи: временные метки и запоздавшие события](../log-timestamps-and-late-events.md).

### Обогащение (Enrichment)

**GeoIP / IP location.** Добавляет геолокацию IPv4/IPv6 из баз MaxMind GeoLite2 City/Country/ASN (лицензия CC BY-SA 4.0). Параметры: `field`, `target_field` (по умолчанию `geoip`), `database_file` (пользовательская `.mmdb`), `properties` (какие поля добавлять), `ignore_missing`. Базы скачиваются автоматически с `https://geoip.elastic.co/v1/database`, если ноды могут обращаться к доменам Elastic GeoIP и выполняется хотя бы один из условий: `ingest.geoip.downloader.eager.download: true` или в кластере есть пайплайн с `geoip`/`ip_location`. Настройки: `ingest.geoip.cache_size` (1000, node-level, общий кэш для всех geoip/ip_location процессоров), `ingest.geoip.downloader.poll.interval` (3d, должен быть > 1d), `ingest.geoip.downloader.enabled` (true). Если нода не может обновлять базы 30 дней, они становятся невалидными и процессор добавляет тег `_ip_location_expired_database` вместо данных. Для ручного управления: отключите downloader и укажите свою базу через `database_file`. Поле `location` **не** индексируется как `geo_point` без явного маппинга. Процессор `ip_location` (9.x) выполняет ту же работу и использует те же базы и настройки.

**User agent.** Параметры: `field`, `target_field` (по умолчанию `user_agent`), `regex_file` (файл в каталоге `config/user-agent*`, создаваемом до старта ES; до 9.4 каталог назывался `config/ingest-user-agent`), `properties` (по умолчанию `[name, os, device, original, version]`), `extract_device_type` (beta), `ignore_missing`. Кэш: `ingest.user_agent.cache_size` (1000). Опция `ecs` удалена в 9.0.

**Enrich.** Подтягивает данные из enrich index во время индексации. Типы политик: `match` (точное значение, term query), `range` (число/дата/IP → диапазон в enrich index), `geo_match` (geo_shape query). Жизненный цикл: создать policy → выполнить → использовать в процессоре.

```bash
# 1. Source index с данными для обогащения
PUT /threat-intel
{ "mappings": { "properties": { "ip": { "type": "ip" }, "threat_level": { "type": "keyword" } } } }

# 2. Политика (типы: match — точное значение, range — диапазон, geo_match — geo_shape)
PUT _enrich/policy/ip-enrichment-policy
{ "match": { "indices": "threat-intel", "match_field": "ip", "enrich_fields": ["threat_level"] } }

# 3. Выполнение (создаёт enrich index)
PUT _enrich/policy/ip-enrichment-policy/_execute

# 4. Процессор в пайплайне
PUT _ingest/pipeline/enrich-threat
{
  "processors": [
    {
      "enrich": {
        "policy_name": "ip-enrichment-policy",
        "field": "source.ip",
        "target_field": "threat_intel",
        "max_matches": 1,
        "ignore_missing": true
      }
    }
  ]
}
```

Параметры процессора: `policy_name`, `field`, `target_field`, `max_matches`, `override`, `ignore_missing`, `spatial_relation` (только для `geo_match`, по умолчанию `intersects`). Обновление политики: создайте и выполните новую, замените `policy_name` в процессорах, удалите старую.

**Сетевые и идентификационные процессоры.**

| Процессор | Назначение | Ключевые параметры |
|-----------|------------|--------------------|
| `community_id` | Community ID для корреляции сетевых потоков (спецификация Community ID); с ECS не требует конфигурации | `source_ip`/`source_port`/`destination_ip`/`destination_port`/`iana_number`/`transport` (дефолты — ECS-поля), `target_field` (`network.community_id`), `seed` (0–65535, защита от коллизий между доменами), `ignore_missing` (true) |
| `fingerprint` | Хэш содержимого документа для дедупликации | `fields` (обязательный, массив), `target_field` (`fingerprint`), `method` (`SHA-1` по умолчанию; `MD5`, `SHA-256`, `SHA-512`, `MurmurHash3`), `salt`, `ignore_missing` |
| `network_direction` | Направление трафика (internal/external) по IP и списку внутренних сетей | `source_ip`, `destination_ip`, `internal_networks`, `target_field` (`network.direction`) |
| `registered_domain` | Извлекает registered domain (eTLD), sub-domain и TLD из FQDN | `field`, `target_field` |
| `set_security_user` | Детали текущего пользователя (username, roles, email, full_name, metadata, api_key, realm, authentication_type) | `target_field` (`user`), `properties` |
| `circle` | Конвертирует location-поле в geo_point | `field`, `radius`, `target_field` |
| `routing` | Устанавливает routing документа | `field` |
| `attachment` | Парсит бинарные данные (PDF, DOCX) через Apache Tika; плагин `ingest-attachment` на всех узлах | `field`, `target_field`, `indexed_chars`, `properties` |

**Redact** — маскирует PII, используя grok-движок: совпадения заменяются на `<имя_паттерна>` (настройка `prefix`/`suffix`). Совместим только с ECS-паттернами. Параметры: `field`, `patterns` (обязательные), `pattern_definitions`, `ignore_missing` (true), `skip_if_unlicensed` (false), `trace_redact` (false — ставит `_ingest._redact._is_redacted`). **Commercial feature**: без подходящей лицензии процессор бросает исключение (либо тихо пропускает документ при `skip_if_unlicensed: true`).

```json
{
  "redact": {
    "field": "message",
    "patterns": ["%{IP:client}", "%{EMAILADDRESS:email}"],
    "prefix": "*",
    "suffix": "*"
  }
}
```

### Фильтрация, условия и управление выполнением

**drop** — отбрасывает документ без ошибки (например, health-check запросы). **fail** — бросает исключение с заданным `message`; полезен для валидации входных данных. **terminate** — прекращает выполнение текущего пайплайна, но документ при этом индексируется (в отличие от `drop`).

**Условная обработка** — `if`/`then`/`else` на каждом процессоре; условие — выражение Painless. Для отсутствующих полей используйте безопасную навигацию `ctx?.field`:

```json
{
  "if": "ctx.level == 'ERROR'",
  "then": [
    { "set": { "field": "priority", "value": "high" } }
  ],
  "else": [
    { "set": { "field": "priority", "value": "normal" } }
  ]
}
```

**Script** — inline или stored скрипт в painless ingest context:

```json
{
  "script": {
    "lang": "painless",
    "source": "ctx.duration_ms = ctx.duration_ns / 1000000;",
    "params": { "divider": 1000000 }
  }
}
```

**for_each** — применяет один процессор к каждому элементу массива или объекта; элемент доступен как `_ingest._value`:

```json
{
  "for_each": {
    "field": "tags",
    "processor": {
      "uppercase": { "field": "_ingest._value" }
    },
    "ignore_missing": false
  }
}
```

**Pipeline** — вызывает другой пайплайн (вложенные пайплайны); имя текущего пайплайна доступно в `_ingest.pipeline`:

```json
{
  "pipeline": {
    "name": "inner-pipeline",
    "ignore_missing_pipeline": false
  }
}
```

**Reroute** — маршрутизирует документ в другой индекс или data stream. Два режима: явный `destination` либо data stream-режим (`dataset`/`namespace`, статические значения или ссылки на поля; тип data stream изменить нельзя — имя должно соответствовать схеме `<type>-<dataset>-<namespace>`). После выполнения `reroute` все оставшиеся процессоры текущего пайплайна пропускаются, включая `final_pipeline`; если пайплайн вызван из `pipeline`-процессора, пропускается и вызывающий пайплайн. Не более одного `reroute` на документ — это позволяет задавать взаимоисключающие условия в стиле if/else-if. Процессор обновляет `data_stream.type/dataset/namespace` и `event.dataset`; документ далее обрабатывается пайплайном новой цели, цепочка продолжается, пока есть подходящий `reroute` (циклы детектируются и приводят к исключению).

```json
{
  "reroute": {
    "tag": "nginx",
    "if": "ctx?.log?.file?.path?.contains('nginx')",
    "dataset": "nginx"
  }
}
```

## Пример: полный пайплайн для веб-логов

```bash
PUT _ingest/pipeline/apache-logs
{
  "description": "Parse Apache combined log format",
  "processors": [
    {
      "grok": {
        "field": "message",
        "patterns": [
          "\\[%{HTTPDATE:timestamp}\\] \"%{WORD:method} %{URIPATH:path} %{DATA:protocol}\" %{INT:status} %{INT:bytes} %{QS:referrer} %{QS:user_agent}"
        ],
        "ignore_failure": true
      }
    },
    {
      "date": {
        "field": "timestamp",
        "target_field": "@timestamp",
        "formats": ["dd/MMM/yyyy:HH:mm:ss Z"],
        "ignore_failure": true
      }
    },
    {
      "convert": {
        "field": "status",
        "type": "integer",
        "ignore_failure": true
      }
    },
    {
      "convert": {
        "field": "bytes",
        "type": "long",
        "ignore_failure": true
      }
    },
    {
      "user_agent": {
        "field": "user_agent",
        "ignore_missing": true,
        "ignore_failure": true
      }
    },
    {
      "remove": {
        "field": ["message", "timestamp"],
        "ignore_failure": true
      }
    }
  ],
  "on_failure": [
    { "set": { "field": "_ingest.failure", "value": "{{_ingest.on_failure_processor_type}}" } },
    { "set": { "field": "_ingest.parse_status", "value": "failed" } }
  ]
}
```

## Тестирование пайплайнов

```bash
# Существующий пайплайн
POST _ingest/pipeline/apache-logs/_simulate
{
  "docs": [
    {
      "_index": "logs",
      "_id": "1",
      "_source": {
        "message": "[25/Aug/2026:14:30:00 +0300] \"GET /api/users HTTP/1.1\" 200 1234 \"-\" \"Mozilla/5.0\""
      }
    }
  ]
}

# Inline-пайплайн без сохранения в cluster state: тело содержит "pipeline" и "docs"
POST _ingest/pipeline/_simulate
{ "pipeline": { "description": "test", "processors": [ ... ] }, "docs": [ ... ] }

# Verbose: результат после каждого процессора
POST _ingest/pipeline/apache-logs/_simulate?verbose=true
```

Ответ содержит итоговый документ: `{"docs": [{"doc": {"_index": ..., "_id": ..., "_source": {...}, "_ingest": {"timestamp": ...}}}]}`. С `verbose=true` — промежуточные результаты каждого процессора. Поддерживаются также GET-формы (`GET _ingest/pipeline/<id>/_simulate`). Если пайплайн содержит `reroute`, симуляция следует за ним к новой цели и выполняет пайплайны новой цели — данные при этом не индексируются. С 9.2 API возвращает 400 на невалидные процессоры. Для построения grok-паттернов есть Grok Debugger в Kibana.

## Обработка ошибок

### Механика on_failure

* Процессор может иметь собственный блок `on_failure` — он выполняется сразу после сбоя процессора. Если `on_failure` указан (даже пустой), оставшиеся процессоры пайплайна **выполняются**.
* Если у процессора нет `on_failure` и `ignore_failure` не `true`, срабатывает pipeline-level `on_failure` (fallback); оставшиеся процессоры после него **не выполняются**.
* Без обоих механизмов весь запрос падает с ошибкой, документ не индексируется.

```json
{
  "grok": {
    "field": "message",
    "patterns": ["%{TIMESTAMP_ISO8601:ts} %{LOGLEVEL:level}"],
    "on_failure": [
      {
        "set": {
          "field": "parse_error",
          "value": "{{_ingest.on_failure_message}}"
        }
      }
    ]
  }
}
```

Метаданные ошибки доступны в шаблонах: `{{_ingest.on_failure_message}}`, `{{_ingest.on_failure_processor_type}}`, `{{_ingest.on_failure_processor_tag}}`.

### DLQ и failure store

**Legacy-паттерн (любой индекс):** маршрутизация неудачных документов в отдельный индекс через pipeline-level `on_failure` и смену `_index`:

```json
"on_failure": [
  {
    "set": {
      "description": "Index document to 'failed-<index>'",
      "field": "_index",
      "value": "failed-{{_index}}"
    }
  }
]
```

**Failure store (data streams, современный механизм):** вторичный набор индексов внутри data stream, в который попадают документы, вызвавшие исключение в пайплайне или конфликтующие с маппингом data stream. Включение:

* Для новых data streams — `data_stream_options.failure_store.enabled: true` в index template (секция `data_stream_options` применяется один раз при создании data stream, в отличие от `settings`/`mappings`, которые применяются при каждом rollover).
* Для существующих — API обновления опций data stream (put data stream options). Для массового включения — кластерная настройка `data_streams.failure_store.enabled` со списком index patterns.

Failure-индексы работают как обычные backing indices: есть write index, поддерживаются rollover и lifecycle policy, создаются лениво при первом неудачном документе. Поиск: `GET <data-stream>::failures/_search`. Привилегии: `read_failure_store` (чтение), `manage_failure_store` (управление). Failure-документ содержит исходный `_source` (изменения пайплайна отбрасываются) плюс диагностику: `error.pipeline`, `pipeline_trace`, `processor_type`, `document.index`.

Failure store можно использовать как источник для правил алертинга в Kibana и для replay: `_reindex` из `<data-stream>::failures` с remediation-пайплайном; процессор `recover_failure_document` преобразует failure-документ обратно в исходный формат. При replay учитывайте, что новые сбои remediation-пайплайна снова попадут в failure store.

## Производительность и масштабирование

### Ingest Node vs Logstash

| Критерий | Ingest Node | Logstash |
|----------|-------------|----------|
| Простота развертывания | Встроен в ES | Отдельный сервис |
| Потребление ресурсов | Минимальное (часть JVM) | Собственная JVM |
| Буферизация | Нет (synchronous) | PQ (persistent queue) |
| Сложная логика | Ограничена процессорами | Полная (Ruby, плагины) |
| Внешние источники | Enrich из индексов | Любые (JDBC, HTTP, Kafka) |
| Масштабирование | Вместе с ES кластером | Независимое |

Logstash может исполнять пайплайны Elasticsearch внутри себя через фильтр `elastic_integration` (GA, требует Logstash 8.7+; при подключении к Elasticsearch 9.2+ версия плагина не ниже 9.2) — это переносит тяжёлую логику (User-Agent, GeoIP) на сторону кластера, сохраняя буферизацию Logstash.

### Когда использовать Ingest Node

- Простой парсинг и обогащение
- Нет необходимости в буферизации
- Минимальная инфраструктура — приоритет
- Beats → Elasticsearch напрямую

### Когда использовать Logstash

- Сложная трансформация данных
- Интеграция с внешними системами (Kafka, JDBC, S3)
- Необходимость буферизации при пиках
- Сложная обработка ошибок с DLQ

### Метрики и ёмкость

```bash
# Глобальные и per-pipeline метрики (count, time_in_millis, current, failed)
GET _nodes/stats/ingest?filter_path=nodes.*.ingest

# Только per-pipeline
GET _nodes/stats?metric=ingest&filter_path=nodes.*.ingest.pipelines
```

Ответ включает `ingest.total` и `ingest.pipelines.<id>` с разбивкой по процессорам — определяет, какие пайплайны запускаются чаще всего и где тратится время. Ingest выполняется на write thread pool (fixed, размер = число процессоров; queue_size 10000 в 8.x–9.1, `max(10000, processors × 750)` в новых версиях): рост `rejected` в `_cat/thread_pool/write` — сигнал перегрузки ingest. При тяжёлой нагрузке выделяют ingest-ноды (`node.roles: [ ingest ]`) и отключают роль на master/data-нодах. Кэши geoip и user_agent (`ingest.geoip.cache_size`, `ingest.user_agent.cache_size`, по умолчанию 1000) — node-level настройки, общие для всех процессоров данного типа на ноде.

## Паттерны и Best Practices

1. **Используйте `ignore_failure: true`** для необязательных процессоров (geoip, user_agent)
2. **`dissect` вместо `grok`** для фиксированных форматов — без регулярных выражений, быстрее
3. **Тестируйте через `_simulate`** перед применением в production; для grok — Grok Debugger
4. **Версионируйте пайплайны** — `version`/`if_version`, `_meta` с владельцем, конфигурации в Git
5. **Мониторьте ingest** через `_nodes/stats/ingest` и write thread pool
6. **Ограничьте сложность Painless-скриптов** — они выполняются в той же JVM, могут влиять на latency
7. **Добавляйте `tag`** к процессорам — идентификатор попадает в метрики и `_ingest.on_failure_processor_tag`
8. **Для data streams включайте failure store** вместо ручной маршрутизации в on_failure
9. **Не изменяйте пайплайны Fleet-интеграций** — Fleet управляет ими через index templates
10. **Маскируйте PII через `redact`** (требуется commercial-лицензия) или выносите маскировку в Logstash

## Troubleshooting

| Симптом | Причина | Решение |
|---------|---------|---------|
| Ошибка при индексации, пайплайн «не найден» | `default_pipeline` ссылается на удалённый или несуществующий пайплайн | Создать пайплайн или изменить настройку индекса (`GET /<index>/_settings`) |
| Весь запрос падает с 500 | Процессор без `on_failure`/`ignore_failure` | Добавить обработку ошибок; текст ошибки — в `_ingest.on_failure_message` |
| grok не матчит строку | Ошибка в паттерне или несовпадение формата | `_simulate` с `verbose`, Grok Debugger, debug-лог `logger.org.elasticsearch.ingest.common.GrokProcessor` |
| geoip не добавляет данные | Базы не обновлялись 30 дней (нет доступа к geoip.elastic.co) | Проверить тег `_ip_location_expired_database`, коннективность; обновить базу вручную через `database_file` |
| enrich падает | Политика не выполнена или enrich index отсутствует | `PUT _enrich/policy/<name>/_execute`; проверить `GET _enrich/_policy` |
| Процессор «не существует» при создании пайплайна | Плагинный процессор не установлен на всех узлах | Установить плагин на все ноды; `plugin.mandatory` для контроля |
| Документы пропадают без ошибок | `drop` или слишком широкое `if`-условие | Проверить условия через `_simulate` |
| Конфликт полей после `dot_expander` | Поле с точкой коллизирует с вложенным объектом (например, `http.host` как текст и как объект) | Переименовать поле перед раскрытием или использовать flexible access pattern |
| redact бросает исключение | Недостаточная лицензия (commercial feature) | `skip_if_unlicensed: true` или подходящая лицензия |
| user_agent/geoip пустые | Исходное поле отсутствует | `ignore_missing: true` |
| reroute не срабатывает | Data stream не соответствует схеме `<type>-<dataset>-<namespace>` | Привести имя в соответствие или использовать явный `destination` |

## Граничные случаи

* Обновление пайплайна не ретроспективно — уже проиндексированные документы не меняются.
* `on_failure` (даже пустой) на процессоре — оставшиеся процессоры пайплайна выполняются; без него — запрос падает целиком.
* `terminate` останавливает пайплайн, но документ индексируется; `drop` — документ не индексируется.
* `reroute`: максимум один на документ, пропускает `final_pipeline`, циклическая маршрутизация — исключение.
* `convert` с `auto` оставляет неконвертируемые значения без изменений.
* `date`: форматы пробуются последовательно; короткие аббревиатуры таймзон неоднозначны.
* `set` с `override: false` не трогает существующие non-null поля.
* Flattened-объекты (поля с точками) требуют `dot_expander` в классическом режиме доступа.
* `geoip`-поле `location` не является `geo_point` без явного маппинга.
* Симуляция следует за `reroute` к новой цели, но ничего не индексирует; с 9.2 невалидные процессоры дают 400.

## См. также

* **[Elasticsearch: Обзор](./elasticsearch_overview.md)** — архитектура кластера, роли узлов.
* **[Logstash: Обзор](../Logstash/logstash_overview.md)** — альтернатива Ingest Pipelines для сложной обработки.
* **[Logstash: Конвейеры и фильтры](../Logstash/logstash_pipelines.md)** — grok, dissect, mutate фильтры.
* **[Grok и Dissect Patterns](../grok_dissect_patterns.md)** — коллекция паттернов для парсинга.
* **[Mapping and Indexing](./elasticsearch_mapping_and_indexing.md)** — маппинг и структуры данных.
* **[Index Templates](./elasticsearch_index_templates.md)** — шаблоны, Data Streams, `default_pipeline` в шаблонах.
* **[ILM и политики хранения](./elasticsearch_ilm_and_retention.md)** — жизненный цикл индексов.
