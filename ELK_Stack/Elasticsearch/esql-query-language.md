# Elasticsearch: ES|QL — конвейерный язык запросов

**Актуально для:** Elasticsearch 9.5.x / 8.19 LTS

## Определения

*   **ES|QL (Elasticsearch Query Language)** — конвейерный (piped) язык запросов для фильтрации, преобразования и аналитики над данными в Elasticsearch. Появился в 8.11, статус GA — с 8.14; в 9.x остаётся основным рекомендуемым языком для аналитики.
*   **Source command** — команда-источник, формирующая входную таблицу (`FROM`, `ROW`, `SHOW`, `TS` (preview 9.2 → GA 9.5), `PROMQL` (GA 9.5)). Обязательный первый элемент запроса.
*   **Processing command** — команда обработки: изменяет строки и столбцы предыдущего шага (`WHERE`, `KEEP`, `DROP`, `SORT`, `STATS`, `EVAL`, `LIMIT`, `GROK`, `DISSECT`, `RENAME`, `MV_EXPAND`, `ENRICH`, `LOOKUP JOIN` (GA 9.0), `DEDUP`, `INLINE`, `RERANK`, `TS_INFO`, `CHANGE_POINT` (preview), `SAMPLE` (preview)).
*   **Pipe (`|`)** — разделитель шагов: результат одного шага становится входом следующего.
*   **Query directive** — необязательная настройка запроса перед source-командой (например, `SET time_zone = "Europe/Moscow";`).
*   **Поколоночный движок (columnar engine)** — способ выполнения запросов «по столбцам»: агрегации и фильтры читают только нужные поля, что и даёт выигрыш против построчного сканирования в аналитических сценариях.

## Основные концепции

### Модель выполнения

Запрос — это таблица плюс конвейер операций над ней:

```esql
FROM logs-*                 -- источник: таблица документов индекса/потока
| WHERE status >= 500       -- фильтрация строк
| STATS errors = COUNT(*) BY host.name   -- агрегация
| SORT errors DESC          -- сортировка результата
| LIMIT 10                  -- обрезка
```

Каждый документ — строка, каждое поле — столбец. ES|QL **не вычисляет relevance score** (`_score`): результат упорядочивается только через явный `SORT`. Для полнотекстового поиска с ранжированием используется Query DSL (см. позиционирование ниже).

### Где ES|QL, а где Query DSL, KQL и Lucene

| Задача | Язык |
|---|---|
| Аналитика в один запрос: фильтр + агрегация + сортировка | **ES\|QL** |
| Быстрая фильтрация в Discover/на дашборде | **KQL** |
| Поиск с relevance-ранжированием, гибридный поиск, кастомный scoring | **Query DSL** |
| Регулярные выражения, fuzzy-матчи «на лету» в строке поиска | **Lucene** |

ES|QL **дополняет, но не заменяет Query DSL**: запись данных через него недоступна, relevance-скор не вычисляется — ES|QL не сортирует результаты по `_score`, ранжирование остаётся за Query DSL. С 9.1 (GA) в ES|QL есть полнотекстовые функции `MATCH`, `MATCH_PHRASE`, `QSTR` и `KQL` — это фильтры полнотекстового совпадения (замена «тяжёлым» `LIKE`/`RLIKE`), но не скоринг; подробно о них и о работе с ними в Discover — в [Kibana: Поиск, визуализация](../Kibana/kibana_search_and_visualization.md). Сравнение с KQL/Lucene и примеры аналитики — там же и в [Elasticsearch: Обзор](./elasticsearch_overview.md).

### Права доступа

*   `POST /_query` и `POST /_query/async` требуют **index privilege `read`** на индексы, data streams, алиасы или views, участвующие в запросе.
*   Cluster privilege `monitor_esql` даёт право только просматривать выполняемые запросы — он **не** даёт возможности запускать запросы или забирать их результаты.

## Практические сценарии

### 1. Первый запрос через REST API

```bash
curl -s -u elastic:$PASS -k -H 'Content-Type: application/json' \
  -X POST "$ES/_query?format=txt" -d '{
  "query": "FROM logs-* | WHERE status >= 500 | STATS e = COUNT(*) BY service.name | SORT e DESC | LIMIT 10"
}'
# → таблица в текстовом формате (format=txt|csv|tsv|md) или JSON columns/values (format=json)
```

Формат ответа задаётся параметром `format` в URL или заголовком `Accept`: структурные (`json`, `yaml` — с метаданными, `columns` + `values`), табличные (`csv`, `tsv`, `txt`, `md` — только данные, удобны для CLI) и бинарные (`cbor`, `smile`, `arrow` — для приложений). По умолчанию возвращаются строки; для `json`/`yaml`/`cbor`/`smile` доступен режим `"columnar": true` (все значения одного столбца одним массивом).

В Kibana Console запрос пишется в тройных кавычках — без экранирования вложенных кавычек:

```json
{
  "query": """
    FROM logs-*
    | WHERE status >= 500
    | STATS errors = COUNT(*) BY service.name
    | SORT errors DESC
    | LIMIT 10
  """
}
```

### 2. Фильтрация и проекция

```esql
FROM logs-app-*
| WHERE @timestamp > NOW() - 15 minutes AND log.level == "ERROR"
| KEEP @timestamp, service.name, message, trace.id
| SORT @timestamp DESC
| LIMIT 50
```

*   `WHERE` — фильтрация строк (в т.ч. `AND`/`OR`/`NOT`, `LIKE`, `RLIKE`, `IN`, `IS NULL`).
*   `KEEP`/`DROP` — выбор/исключение столбцов: не тащите лишние поля, это прямой выигрыш в объёме ответа.
*   `RENAME`, `MV_EXPAND` (разворот массива в строки) — преобразование структуры.

### 3. Агрегации: `STATS` и временные корзины

```esql
-- топ сервисов по количеству ошибок
FROM logs-app-*
| WHERE log.level == "ERROR"
| STATS errors = COUNT(*) BY service.name
| SORT errors DESC
| LIMIT 5

-- ошибки по 5-минутным корзинам (BUCKET вместо ручного DATE_TRUNC)
FROM logs-app-*
| WHERE log.level == "ERROR"
| STATS errors = COUNT(*) BY bucket = BUCKET(@timestamp, 5 minutes)
| SORT bucket ASC
```

`STATS ... BY` группирует строки; без `BY` агрегат считается по всей выборке. Фильтр внутри агрегата: `STATS avg = AVG(duration) WHERE status == 200`. Эквивалент семантики Query-DSL-агрегаций — в [Aggregations](./elasticsearch_aggregations.md); сравнительная таблица подходов — в [Kibana: Поиск и визуализация](../Kibana/kibana_search_and_visualization.md).

### 4. Парсинг строк прямо в запросе

```esql
FROM nginx-access-*
| DISSECT message "%{client_ip} - - [%{ts}] \"%{method} %{uri} %{proto}\" %{status} %{bytes}"
| WHERE status >= 500
| STATS total = COUNT(*) BY uri
| SORT total DESC
| LIMIT 20
```

Команды `GROK` и `DISSECT` работают как processing-команды (не как фильтры Logstash): парсинг происходит в момент выполнения запроса, ничего не пишется в индекс. Для постоянной обработки при индексации используйте [Ingest Pipelines](./elasticsearch_ingest_pipelines.md) и [Grok/Dissect](../grok_dissect_patterns.md).

### 5. Сочетание с Query DSL через параметр `filter`

```json
{
  "query": "FROM logs-* | STATS c = COUNT(*) BY service.name",
  "filter": { "range": { "@timestamp": { "gte": "now-1h" } } }
}
```

Параметр `filter` (Query DSL) отсекает документы **до** выполнения ES|QL-конвейера и, в отличие от `WHERE`, способен исключить целые индексы из выборки — полезно, когда часть индексов паттерна замаплена с конфликтующими типами полей.

### 6. Долгие и асинхронные запросы

```json
POST /_query/async
{
  "query": "FROM logs-* | STATS c = COUNT(*) BY service.name",
  "wait_for_completion_timeout": "2s",
  "keep_on_completion": true
}
# → {"id": "...", "is_running": true}   — если за 2s не успел
```

Дальше — `GET /_query/async/{id}?wait_for_completion_timeout=10s` (прогресс и результат), `DELETE /_query/async/{id}` (остановить и забрать частичный результат), `POST /_query/async/{id}/_stop` (остановить без возврата результатов). Идентификатор и статус дублируются в заголовках `X-Elasticsearch-Async-Id` / `X-Elasticsearch-Async-Is-Running` — они удобны, когда тело ответа в табличном формате (`csv`, `txt`).

`keep_on_completion: true` сохраняет результаты даже при успешном завершении в течение `wait_for_completion_timeout` — удобно для отложенного анализа. Хранение ограничено `keep_alive` (по умолчанию 5 дней).

Начиная с 9.5, дополнительные управляющие endpoints:

| Метод | Путь | Назначение | Привилегия |
|---|---|---|---|
| `POST` | `/_query/async` | Submit async query | `read` на индексы |
| `GET` | `/_query/async/{id}` | Get results / статус | `read` на индексы (только владелец) |
| `DELETE` | `/_query/async/{id}` | Cancel + delete | `cancel_task` (или владелец) |
| `POST` | `/_query/async/{id}/_stop` | Stop без возврата результатов | `cancel_task` (или владелец) |
| `GET` | `/_esql/queries` | Список всех running queries | `monitor_esql` |
| `GET` | `/_esql/queries/{id}` | Инфо о конкретном запросе | `monitor_esql` |

ES|QL накладывает лимиты на размер результата для защиты кластера. Без явного `LIMIT` запрос получает **1000 строк** по умолчанию; максимум — 10 000. Для time-series запросов (`TS`/`PROMQL`) лимиты выше: 10 000 по умолчанию, до 10 000 000. Подробные настройки (`esql.query.result_truncation_*`, `esql.query.allow_partial_results`) — в [Kibana: Поиск и визуализация](../Kibana/kibana_search_and_visualization.md) (строка 113/118). Дополнительная API-специфичная настройка:

| Настройка | По умолчанию | Описание |
|---|---|---|
| `esql.query.queue_capacity` | 32 | Количество ES|QL запросов в очереди на узле; при переполнении новые запросы отклоняются с ошибкой |

### 7. Параметризация запросов (защита от инъекций и переиспользование)

```json
{
  "query": "FROM logs-* | WHERE service.name == ?name | STATS COUNT(*)",
  "params": [{ "name": "payments-api" }]
}
```

`?` подставляет литерал (значение), `??` (preview с 9.1) — идентификатор: имя поля или функции. Именованные (`?name`), позиционные (`?1`) и анонимные (`?`) стили параметров нельзя смешивать в одном запросе.

### 8. Встраивание в компоненты стека

*   **Discover (Kibana)** — переключатель языка в строке поиска; синтаксис и сравнение языков — в [Kibana: Поиск и визуализация](../Kibana/kibana_search_and_visualization.md).
*   **Alerting** — правило `.es-query` с `searchType: esqlQuery` (GA в правиле с 9.2), для ES|QL задаются time field и группировка — см. [Alerting](./elasticsearch_alerting.md).
*   **Dev Tools / CLI** — основной способ отладки; `curl`-пример выше для скриптов.

## Устранение неполадок

| Симптом | Причина | Решение |
|---|---|---|
| `unknown column [x]` | Опечатка в имени поля или поле отсутствует в части индексов паттерна | Проверить маппинг (`GET logs-*/_mapping/field/x*`); учесть, что поля, отсутствующие в части индексов, могут вернуться как `unsupported` |
| `security_exception ... missing [read] index privilege` | Недостаточно прав на индексы запроса | Выдать privilege `read` на целевые индексы/data streams роли пользователя |
| `is_partial: true` в ответе | Часть шардов недоступна (rolling upgrade, red-индекс) | `allow_partial_results` включён по умолчанию (`true`, 8.19/9.1+); для строгого результата выставить `allow_partial_results: false` в запросе или `esql.query.allow_partial_results: false` на кластере — дождаться полного восстановления (см. также [Kibana: Поиск и визуализация](../Kibana/kibana_search_and_visualization.md)) |
| Запрос «висит» на больших данных | Полное сканирование без сужения по времени | Сузить диапазон через `WHERE @timestamp`/параметр `filter`, уменьшить выборку (`KEEP`, `LIMIT`), для длинных запросов — async (`/_query/async`) |
| Результат ограничен 1000 строками | Без `LIMIT` ES|QL возвращает max 1000 строк (default) | Добавить `LIMIT N` или изменить `esql.query.result_truncation_default_size` на кластере |
| `result_truncation_exception` | Превышен `esql.query.result_truncation_max_size` (10 000) | Обязательно `LIMIT` в аналитических запросах; для больших выборок — экспортировать через `/_query/async` + `columnar: true` |
| Медленный `STATS` по широким данным | Тяжёлые функции (`GROK` и др.), много загружаемых значений | Смотреть `documents_found` / `values_loaded` в ответе (с 9.1): высокие значения — сигнал, что запрос загружает много значений на документ |
| Тип колонки `unsupported` | Конфликт типов поля между индексами паттерна | Метаданные `original_types` в колонке подсказывают исходные типы; сузить паттерн, исправить маппинг или привести тип через `filter`/`EVAL ... ::type` |
| Ожидание `now()` в тестах возвращает пусто | Запрос по индексам без документов в окне | Проверить `@timestamp` данных; в Dev Tools использовать явные даты вместо `NOW()` |

## Best Practices

*   **Сужайте по времени первым шагом**: `WHERE @timestamp > NOW() - 30 minutes` (или параметр `filter`) — до любых вычислений.
*   **`KEEP` вместо `SELECT *`**: возвращайте только нужные столбцы.
*   **Явный `LIMIT`** в ad-hoc запросах — без него ES|QL возвращает max 1000 строк; для аналитики с большим объёмом используйте async + `columnar: true` и настройте `esql.query.result_truncation_*`.
*   **Не используйте ES|QL там, нужен score**: полнотекстовый поиск, relevance-тюнинг и запись — Query DSL ([Query DSL](./elasticsearch_query_dsl.md)).
*   **Для экспорта/фоновых задач — async** с `keep_on_completion: true`: не блокируйте соединение ожиданием длинного запроса; результаты сохраняются до `keep_alive` (по умолчанию 5 дней), забираются через `GET /_query/async/{id}`.
*   **Параметризуйте** значения, приходящие из пользовательского ввода (`?`/`??`), вместо конкатенации строк.
*   **Отлаживайте в Console с автодополнением** — оно подсказывает команды, функции и поля.
*   **Следите за queue_capacity**: при высокой нагрузке ES|QL запросы могут отклоняться (`esql.query.queue_capacity` по умолчанию 32); мониторьте через `GET /_esql/queries` (9.5+).

## Дополнительная информация

*   **[Elasticsearch: Обзор](./elasticsearch_overview.md)** — определение ES\|QL, пример аналитики, ограничения относительно Query DSL, гибридный поиск с retrievers.
*   **[Kibana: Поиск, визуализация и управление](../Kibana/kibana_search_and_visualization.md)** — таблица сравнения KQL / Lucene / ES\|QL, синтаксис KQL, режимы Discover.
*   **[Alerting: Kibana Alerting и Watcher](./elasticsearch_alerting.md)** — правила `.es-query` на ES\|QL (`esqlQuery`), экспериментальная система алертинга на ES\|QL (9.5+).
*   **[Aggregations](./elasticsearch_aggregations.md)** — агрегативная аналитика Query DSL (эквивалент `STATS`).
*   **[Query DSL](./elasticsearch_query_dsl.md)** — язык запросов с relevance-скорингом.
*   **Kubernetes: [Kibana Guide](../../Kubernetes/MonitoringLogging/EFK/kibana_guide.md)** — примеры ES\|QL-запросов поверх логов Kubernetes.

### Перекрытие с существующими файлами (§0.10)

Проверенные файлы при поиске перекрытий (grep + RAG по базе):

*   `ELK_Stack/Elasticsearch/elasticsearch_overview.md` — определение ES\|QL и один практический пример; настоящий файл — справка по самому языку (модель, команды, API, права, асинхронность). Пример в overview сохранён, добавлена ссылка сюда.
*   `ELK_Stack/Kibana/kibana_search_and_visualization.md` — большой раздел «Архитектура ES\|QL» (таблица команд с версиями, multivalue, EVAL vs runtime fields, ENRICH/LOOKUP JOIN, полнотекстовые функции 9.1) плюс SSoT по сравнению языков Discover (KQL/Lucene/ES\|QL) и синтаксису KQL. Разделы охватывают язык в Kibana-контексте; настоящий файл — REST API-справочник (форматы ответа, права, async, параметризация, `filter`-параметр, управляющие endpoints 9.5+). Общие факты не дублируются: лимиты вывода (`LIMIT`/`esql.query.result_truncation_*`) и `allow_partial_results` — SSoT в kibana_search_and_visualization.md (см. строку 113/118); здесь — только ссылка и кластерные настройки (`esql.query.queue_capacity`, `monitor_esql`/`cancel_task` привилегии, `_stop` endpoint). Явных противоречий не обнаружено (сверены `allow_partial_results`, статус GA 8.14, `MATCH`-функции).
*   `ELK_Stack/Kibana/kibana_overview.md`, `ELK_Stack/elk_stack_overview.md` — определения термина; не дублируются.
*   `ELK_Stack/Elasticsearch/elasticsearch_alerting.md` — SSoT по интеграции ES\|QL с правилами; здесь только ссылка.
*   `Kubernetes/MonitoringLogging/EFK/kibana_guide.md` — примеры запросов в контексте Kubernetes-логов; оставлены там как контекстные, добавлена ссылка на настоящий файл.
*   Дублирования не требуется: полноценного описания языка в базе не существовало (проверено grep `ES|QL` по всей базе и RAG-поиском).
