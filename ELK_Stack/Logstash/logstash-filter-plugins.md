# Logstash: Фильтры mutate, парсинг и обогащение

**Актуально для:** Logstash 8.19 (LTS) / 9.5.x (плагины: mutate 3.6.0, json 3.2.1, kv 4.7.0, csv 3.1.2, elasticsearch 4.4.1, geoip 8.0.0, useragent 3.3.5, cidr 3.2.0, syslog_pri 3.2.1, urldecode 3.0.6)

## Определения

**mutate** — фильтр структурных преобразований полей события (переименование, приведение типов, разбиение/склейка строк, подстановка по регулярному выражению) без разбора содержимого лога.

**Фильтр-обогащение (enrichment)** — плагин, добавляющий в событие данные из внешнего источника: базы IP-геолокации (`geoip`), других индексов Elasticsearch (`elasticsearch`), словарей (`translate`).

**Тег обработки ошибок (failure tag)** — метка в `[tags]`, добавляемая событию при неудаче плагина. Основные: `_mutate_error`, `_jsonparsefailure`, `_timestampparsefailure`, `_kv_filter_error`, `_kv_filter_timeout`, `_geoip_lookup_failure`, `_geoip_expired_database`, `_elasticsearch_lookup_failure`, `_syslogpriparsefailure`, `_urldecodefailure`.

**GeoLite2 / GeoIP2** — базы IP-геолокации MaxMind: GeoLite2 (City, Country, ASN) — бесплатные, GeoIP2 (City, ISP, Domain, Enterprise, Anonymous-IP) — коммерческие. Плагин `geoip` поставляется со встроенной базой GeoLite2 City.

**ECS-совместимость плагина** — режим опции `ecs_compatibility` (`disabled` / `v1` / `v8`), наследуется из настройки `pipeline.ecs_compatibility`; меняет целевую структуру результатов и заставляет явно задавать `target` у ряда плагинов.

**ES|QL** — SQL-подобный запросный язык Elasticsearch; в фильтре `elasticsearch` доступен в режиме Technical Preview (`query_type => "esql"`).

## Основные концепции

### mutate — структурные преобразования полей

Единственный плагин для «ремонта» событий на лету: приведение типов, чистка полей, переименование под схему. Внутри одного блока `mutate` операции выполняются **в фиксированном порядке**, независимо от порядка их записи:

```
coerce → rename → update → replace → convert → gsub → uppercase → capitalize →
lowercase → strip → split → join → merge → copy
```

Если последовательность операций имеет значение, каждый вид мутации помещается в **отдельный блок** `mutate`:

```ruby
filter {
  mutate {
    split => { "hostname" => "." }
    add_field => { "shortHostname" => "%{[hostname][0]}" }
  }
  mutate {
    rename => { "shortHostname" => "hostname" }
  }
}
```

Здесь `rename` должен увидеть уже созданное `shortHostname`, поэтому он вынесен в следующий блок.

Ключевые операции:

| Опция | Тип | Семантика |
| :--- | :--- | :--- |
| `convert` | hash | Приведение типа: `integer`, `integer_eu`, `float`, `float_eu`, `string`, `boolean`. Массивы конвертируются поэлементно, хэши — без действия. Дробные значения при переводе в `integer` усекаются; `float` даёт double IEEE 754 (для точности в маппинге Elasticsearch используйте `double`) |
| `rename` | hash | Переименование. Если целевое поле существует — оно перезаписывается; если исходного нет — операция не выполняется и тег не ставится. Порядок при множественных переименованиях не гарантирован |
| `replace` | hash | Заменяет значение поля **или создаёт поле, если его нет**; поддерживает подстановку `%{foo}` из других полей |
| `update` | hash | Обновляет **только существующее** поле; если поля нет — действие не выполняется |
| `coerce` | hash | Значение по умолчанию для поля, которое существует, но равно `null` |
| `copy` | hash | Копия поля; целевое перезаписывается |
| `gsub` | array | Замена по регулярному выражению: плоский массив троек `["поле", "паттерн", "замена", ...]`. Работает только со строками и массивами строк; экранируйте обратные слэши в конфиге |
| `split` / `join` | hash | Разбиение строки в массив по разделителю / склейка массива в строку |
| `merge` | hash | Слияние массивов или хэшей: `array + string` работает, `string + string` даёт массив из двух элементов, `array + hash` — не работает |
| `strip` | array | Обрезка краевых пробелов у перечисленных полей |
| `lowercase` / `uppercase` / `capitalize` | array | Регистр строк перечисленных полей |

При сбое внутри блока остальные операции этого блока **прерываются**, событие получает тег `tag_on_failure` (по умолчанию `_mutate_error`; в отличие от большинства фильтров, здесь это строка, а не массив).

Общие для всех фильтров опции: `add_field`, `add_tag`, `remove_field`, `remove_tag`, `id` (именованный инстанс для мониторинга), `enable_metric`, `periodic_flush`.

### Фильтр json — разбор JSON

Берёт JSON-строку из поля `source` и разворачивает её в структуру события:

```ruby
filter {
  json {
    source => "message"   # обязательно
    target => "app"       # по умолчанию разворачивает в корень события
  }
}
```

* При неудаче разбора событие остаётся нетронутым и получает тег `_jsonparsefailure` (значение `tag_on_failure`). Опция `skip_on_invalid_json => true` (по умолчанию `false`) позволяет молча пропускать невалидный JSON — удобно для смешанных потоков, где JSON ожидается не всегда.
* Если в разобранном JSON есть поле `@timestamp`, плагин применяет его к `@timestamp` события. При неудаче разбора времени поле переименовывается в `_@timestamp`, а событие получает тег `_timestampparsefailure`.
* Существующее поле `target` перезаписывается. При включённом ECS без `target` плагин пишет предупреждение — задавайте `target` явно.

### Фильтр kv — парсинг key=value

Разбирает строки вида `ip=1.2.3.4 error=REFUSED` (postfix, iptables, аргументы командной строки, query string):

```ruby
filter {
  kv { }   # source по умолчанию "message"
}
```

Разделители:

* `field_split` (по умолчанию `" "`) — символы-разделители между парами; строка трактуется как символьный класс regex, поэтому `[`, `]` и прочие спецсимволы экранируются через `\`. Для query string: `field_split => "&?"`.
* `value_split` (по умолчанию `"="`) — разделитель ключа и значения внутри пары.
* `field_split_pattern` / `value_split_pattern` — regex-разделители для многосимвольных разделителей; имеют приоритет над односимвольными.

Полезные опции: `target` (нет — пары в корень события; при ECS без `target` — предупреждение), `include_keys` / `exclude_keys`, `prefix`, `recursive` (углубляться в значения, по умолчанию `false`), `transform_key` / `transform_value` (`lowercase` / `uppercase` / `capitalize`), `trim_key` / `trim_value` (обрезка краевых символов), `remove_char_key` / `remove_char_value` (удаление символов в любом позиции), `allow_duplicate_values` (`true` — дубли складываются в массив), `allow_empty_values` (`false`), `default_keys`, `whitespace` (`lenient` по умолчанию / `strict`), `include_brackets` (`true` — символы `()`, `[]`, `<>` считаются обёрткой значения и удаляются; `false` — остаются частью значения).

Защита от патологических регулярок: `timeout_millis` (по умолчанию 30000 мс, `0` — отключить) с тегом `_kv_filter_timeout`; исключение при разборе — тег `_kv_filter_error` (`tag_on_failure`).

### Фильтр csv — разбор CSV

```ruby
filter {
  csv {
    source => "message"          # по умолчанию "message"
    target => "csv"              # без него — в корень события (предупреждение при ECS)
    columns => ["ts", "method", "path", "status"]
    convert => { "status" => "integer" }
  }
}
```

| Опция | По умолчанию | Примечание |
| :--- | :--- | :--- |
| `separator` | `","` | Любой разделитель; для табуляции указывается реальный символ табуляции, не `\t` |
| `quote_char` | `"` | Символ кавычек |
| `columns` | `[]` | Без списка — имена `column1`, `column2`…; лишние колонки автонумеруются |
| `autogenerate_column_names` | `true` | `false` — колонки без заданных имён не парсятся |
| `autodetect_column_names` | `false` | Имена из заголовка; требует `pipeline.workers => 1` |
| `skip_header` | `false` | Пропуск строки заголовка; также требует `pipeline.workers => 1` |
| `convert` | `{}` | `integer`, `float`, `date`, `date_time`, `boolean` |
| `skip_empty_columns` / `skip_empty_rows` | `false` | Пустые строки при `skip_empty_rows` получают тег `_csvskippedemptyfield` — их можно отсечь условием |

### Фильтр elasticsearch — обогащение из кластера

Ищет ранее проиндексированное событие в Elasticsearch и копирует поля из результата в текущее событие. Классический паттерн — корреляция `start`/`end` с расчётом длительности:

```ruby
filter {
  if [type] == "end" {
    elasticsearch {
      hosts => ["es-server"]
      query => "type:start AND operation:%{[opid]}"   # sprintf-подстановка полей события
      fields => { "@timestamp" => "started" }
    }

    date { match => ["[started]", "ISO8601"] target => "[started]" }

    ruby { code => "event.set('duration_hrs', (event.get('@timestamp') - event.get('started')) / 3600)" }
  }
}
```

Ключевые опции:

| Опция | По умолчанию | Назначение |
| :--- | :--- | :--- |
| `hosts` | `["localhost:9200"]` | Кластеры для поиска |
| `index` | `""` (все индексы) | Список индексов через запятую; поддерживает sprintf-подстановку |
| `query` | — | `query_string`-запрос DSL **или** ES|QL (см. `query_type`) |
| `query_template` | — | Файл с полным DSL-JSON; поля события подставляются в шаблон на каждое событие. Вместе с `query` не используется; `result_size` и `sort` при этом задаются внутри шаблона |
| `query_type` | `dsl` | `dsl` или `esql` |
| `result_size` | `1` | Сколько результатов вернуть |
| `sort` | `"@timestamp:desc"` | Сортировка `<поле>:<направление>`; `enable_sort` (`true`) |
| `fields` | — | Маппинг `"путь.в.результате" => "[поле][на][событии]"` — какие поля копировать |
| `docinfo_fields` / `aggregation_fields` | — | Копирование `_source`-метаданных / результатов агрегаций |
| `target` | — | Куда складывать результат; без него — корень события. Пути из `fields` относительно `target` |
| `retry_on_failure` | `0` (выключен) | Число повторов запроса; `retry_on_status` — коды HTTP для повторов |
| `tag_on_failure` | `["_elasticsearch_lookup_failure"]` | Тег при неудаче поиска |

Аутентификация — один из вариантов: `user` + `password`, `cloud_auth`, `api_key` (формат `id:api_key`, base64-пара или облачный ключ `essu_`). Подключение к Elastic Cloud задаётся отдельной опцией `cloud_id`. Для защищённого кластера нужны права: `read` на индекс и `monitoring` на кластер (для периодических проверок соединения). TLS: `ssl_enabled`, `ssl_certificate_authorities` или keystore/truststore (`ssl_keystore_path` / `ssl_keystore_password`), `ssl_verification_mode` (`full` по умолчанию; `none` отключает проверку сертификатов).

**ES|QL (Technical Preview):** работает с Logstash 8.17.4+ и Elasticsearch 8.11+; `query_type => "esql"`, именованные параметры — `query_params`, размер результата — в `[@metadata][total_values]`. Результат складывается в `target` (без него — только первая строка результата в корень). При multi-fields/подобъектах индекса плагин игнорирует подполя с предупреждением — решается через `KEEP` / `RENAME` / `DROP` в самом запросе.

Важно: запрос выполняется **на каждое событие**, прошедшее в ветку. Это сетевой вызов и поиск по индексу — плагин предназначен для редких событий (конец транзакции), а не для потока в несколько тысяч событий в секунду.

### Фильтр geoip — обогащение по IP-адресу

```ruby
filter {
  geoip {
    source => "clientip"   # обязательно; у массива берётся первое значение
    # target => "geoip"    # по умолчанию при ecs_compatibility => "disabled"
  }
}
```

**Базы.** Плагин встроен в дистрибутив с базой GeoLite2 City; опция `default_database_type` выбирает между встроенными `City` (по умолчанию) и `ASN`. Свои базы задаются опцией `database`: бесплатные `GeoLite2-City`, `GeoLite2-Country`, `GeoLite2-ASN` и коммерческие `GeoIP2-City`, `GeoIP2-ISP`, `GeoIP2-Country`, `GeoIP2-Domain`, `GeoIP2-Enterprise`, `GeoIP2-Anonymous-IP`. Начиная с версии 4.0.0 поддерживаются IPv4 и IPv6 (более старые версии — только IPv4).

**Опции:** `source` (обязательный), `target`, `database`, `default_database_type`, `fields` (список полей результата), `ecs_compatibility`, `tag_on_failure` (`["_geoip_lookup_failure"]`), `cache_size`.

**Кэш.** GeoIP-запрос дорог, поэтому результаты кэшируются: `cache_size` (по умолчанию `1000`). Политики вытеснения нет — при заполнении кэша новые записи в него не добавляются. Кэш общий для всех инстансов фильтра одного типа; побеждает последний объявленный `cache_size`.

**ECS и маппинг полей.** При `ecs_compatibility => "disabled"` (и явном отсутствии `target`) результат идёт в `geoip`; при включённом ECS поле `target` вычисляется из `source`: если `source` — `[client][ip]`, то `target` автоматически становится `client`, и геоданные оказываются в `[client][geo]`; иначе `target` обязателен (допустимые значения: `client`, `destination`, `host`, `observer`, `server`, `source`). Основные соответствия:

| Поле базы | ECS-поле (относительно `target`) |
| :--- | :--- |
| `city_name` | `[geo][city_name]` |
| `country_name` / `country_code2` | `[geo][country_name]` / `[geo][country_iso_code]` |
| `region_name` / `region_iso_code` | `[geo][region_name]` / `[geo][region_iso_code]` |
| `location` / `latitude` + `longitude` | `[geo][location]` (GeoJSON) / `[geo][location][lat]`, `[geo][location][lon]` |
| `timezone` / `postal_code` | `[geo][timezone]` / `[geo][postal_code]` |
| `asn` / `as_org` | `[as][number]` / `[as][organization][name]` |
| `domain` | `[domain]` |

`location` — составное поле (заполняется только при наличии и широты, и долготы); для City-базы при отсутствии пары lat/lon обогащение прерывается. Благодаря GeoJSON-формату `[target][location]` маппится шаблоном elasticsearch output в тип `geo_point` — работают пространственные запросы Kibana.

**Лицензия и автообновление баз.** MaxMind распространяет базы по EULA: обновление базы обязательно в течение 30 дней после её выхода. Управление:

* Включение автообновления в `logstash.yml` (по умолчанию включено — `xpack.geoip.downloader.enabled`) означает ежедневную проверку обновлений у эндпоинта Elastic и замену базы на лету, без остановки фильтра. При первом скачивании происходит переход с CC-базы на EULA-базу.
* Если после перехода на EULA-базу 30 дней не удавалось проверить обновления, обогащение **прекращается** ради соблюдения лицензии; такие события получают тег `_geoip_expired_database`.
* Air-gapped: `xpack.geoip.downloader.enabled: false` — тогда базы под CC-лицензией используются неограниченно, а скачанные EULA-базы удаляются. Прокси — через переменную окружения `http_proxy`.
* Свой источник обновлений: скачать `GeoLite2-ASN.mmdb` и `GeoLite2-City.mmdb`, выполнить из каталога Elasticsearch `./bin/elasticsearch-geoip -s my/database/dir`, раздать файлы статическим HTTP-сервером и указать `xpack.geoip.download.endpoint=http://host/overview.json`.
* Если `database` указывает на пользовательский путь — автообновление отключается, актуальность базы на операторе.

**Мониторинг:**

```bash
curl -XGET 'localhost:9600/_node/stats/geoip_download_manager?pretty'
# → database.City.status: init | up_to_date | to_be_expired | expired
#   database.*.fail_check_in_days, download_stats.successes/failures,
#   download_stats.status: updating | succeeded | failed
```

### Фильтры-спутники: useragent, cidr, syslog_pri, urldecode

Эти плагины закрывают частные, но повторяющиеся задачи разбора и обогащения и обычно используются вместе с `grok`/`kv`/`json`.

**useragent — разбор строки User-Agent.** Плагин `useragent` (v3.3.5) разбирает UA-строку по базе ua-parser (`regexes.yaml`, лицензия Apache 2.0) и раскладывает её на браузер, версию, ОС и тип устройства:

```ruby
filter {
  useragent {
    source => "[user_agent][original]"   # обязательно
    target => "user_agent"               # при ECS это значение по умолчанию
  }
}
```

* Опции: `source` (обязательна; у массива берётся первое значение), `target` (в ECS по умолчанию `user_agent`, иначе — корень события), `regexes` (свой файл правил), `prefix` (строка-префикс к именам извлечённых полей, по умолчанию пустая), `lru_cache_size` (по умолчанию `100000`).
* Разбор UA дорог, поэтому результат кэшируется LRU-кэшем; как и у `geoip`, кэш **общий** для всех инстансов фильтра, побеждает последний объявленный `lru_cache_size`.
* Маппинг полей при `ecs_compatibility => "disabled"`: `name`, `version`, `major`, `minor`, `os_name`, `os_version`, `os_full`, `os_major`, `os_minor`, `device` — в корне события. При ECS: `[user_agent][name]`, `[user_agent][version]`, `[user_agent][os][name|version|full]`, `[user_agent][device][name]`, а части версии (`major`/`minor`/`patch`) кладутся в `[@metadata][filter][user_agent]` и наружу не пишутся.
* Аналог для Elasticsearch — процессор [`user_agent`](../Elasticsearch/elasticsearch_ingest_pipelines.md); фильтр нужен, когда обогащение делается на стороне Logstash (до отправки в кластер) либо UA-данные нужно хранить в отдельном поле.

**cidr — проверка IP по списку сетей.** Фильтр `cidr` (v3.2.0) сопоставляет один или несколько адресов события со списком сетей CIDR; при совпадении навешивает теги/поля. Промах (адрес не попал ни в одну сеть) — не ошибка, тег при этом не ставится:

```ruby
filter {
  cidr {
    address => [ "%{src_ip}", "%{dst_ip}" ]   # или address_field => "[source][ip]"
    network => [ "10.0.0.0/8", "192.168.0.0/16", "fe80::/64" ]
    add_tag => [ "internal" ]
  }
}
```

* Опции: `address` (массив значений; поддерживает sprintf), `address_field` (поле события), `network` (массив сетей), `network_path` (файл со списком сетей), `refresh_interval` (перечитка файла, по умолчанию 600 с), `separator` (разделитель сетей в файле, по умолчанию `\n`). `network` и `network_path` **взаимоисключающи** — одновременное указание является ошибкой.
* Списки сетей удобно держать во внешнем файле (`network_path`) и обновлять его без правки pipeline.

**syslog_pri — разбор PRI заголовка RFC3164.** Фильтр `syslog_pri` (v3.2.1) читает числовой PRI из начала syslog-сообщения и по формуле `priority = facility × 8 + severity` раскладывает его на facility и severity:

```ruby
filter {
  syslog_pri { }   # поле PRI по умолчанию "syslog_pri"
}
```

* Опции: `syslog_pri_field_name` (имя поля с PRI; по умолчанию `syslog_pri`, при ECS — `[log][syslog][priority]`), `use_labels` (`true` — добавлять человекочитаемые названия), `facility_labels` / `severity_labels` (свои таблицы меток из RFC3164).
* При ECS результат раскладывается по схеме: код severity — `[log][syslog][severity][code]`, метка — `[log][syslog][severity][name]`, аналогично facility — `[log][syslog][facility][code]` / `[log][syslog][facility][name]`. Без ECS — плоские `syslog_severity_code`, `syslog_severity`, `syslog_facility_code`, `syslog_facility`.
* Если PRI в сообщении отсутствует, используется значение по умолчанию 13 (`user.notice`). При `use_labels => true` и неизвестном коде facility событие получает тег `_syslogpriparsefailure`.

**urldecode — декодирование URL-encoded значений.** Фильтр `urldecode` (v3.0.6) восстанавливает percent-encoding (`%20`, `%C3%A9`) в заданном поле или во всех полях события:

```ruby
filter {
  urldecode {
    field => "query_string"   # по умолчанию "message"
  }
}
```

* Опции: `field` (по умолчанию `message`), `all_fields` (`true` — декодировать все поля события, по умолчанию `false`), `charset` (кодировка результата, по умолчанию `UTF-8`; важно для источников в Latin-1/`cp1252`), `tag_on_failure` (по умолчанию `["_urldecodefailure"]`, ставится при исключении).
* Строки без `%XX`-последовательностей возвращаются без изменений; значения не-строковых типов не трогаются, массивы и хэши обходятся поэлементно.

## Практические сценарии

### Разбор потока с фолбэком и чистка полей

```ruby
filter {
  # структурированный вход: JSON или key=value — каждый в своё поле
  if [message] =~ /^\{/ {
    json { source => "message" target => "app" }
  } else if [message] =~ /\w+=/ {
    kv { source => "message" target => "app" }
  } else {
    mutate { add_tag => ["unparsed"] }
  }

  if [app] {
    mutate {
      convert => { "[app][status]" => "integer" }   # числовые статусы — для фильтрации и сортировки
      remove_field => ["[app][raw]"]                # сырое поле больше не нужно
    }
  }
}
```

Разбор по условию исключает ложные срабатывания `kv` на JSON-строках (и наоборот), а тег `unparsed` выводит неразобранный хвост наружу вместо молчаливой потери.

### Обогащение GeoIP только для релевантных событий и режим ECS

```ruby
filter {
  if [source][ip] {
    geoip {
      source => "[source][ip]"
      ecs_compatibility => "v8"
      # ECS: [source][ip] -> target "source" -> результат в [source][geo]
    }
  }

  if [source][geo][continent_code] == "EU" {
    mutate { add_tag => ["geo_eu"] }
  }

  if "_geoip_lookup_failure" in [tags] {
    mutate { add_field => { "[@metadata][route]" => "geo_failed" } }
  }
}
```

`geoip` — дорогой плагин (см. flow-метрики в [заметке о конвейерах](./logstash_pipelines.md#диагностика-узкого-места-через-flow-metrics)), поэтому его вызов всегда ограничен условием по наличию IP.

### Корреляция start/end с расчётом длительности

Полный рабочий пример — в разделе [Фильтр elasticsearch](#фильтр-elasticsearch--обогащение-из-кластера) выше: событие `end` ищет парное `start` по `operation:%{[opid]}`, копирует `@timestamp` найденного события в поле `started` и вычисляет длительность через `ruby`. Результат можно писать в поле события и использовать в алертах (`if [duration_hrs] > 1`).

### Валидация цепочки фильтров на одной строке

```bash
# прогнать образец через цепочку и посмотреть итоговое событие и теги
echo 'ip=1.2.3.4 error=REFUSED' | bin/logstash -e '
  input { stdin {} }
  filter { kv { } geoip { source => "ip" } }
  output { stdout { codec => rubydebug } }'
# → в выводе: ip, error, geoip.* и отсутствие тегов _kv_filter_error / _geoip_lookup_failure
```

Способы отладки (синтаксическая проверка `-t`, запуск одного конфига, P2P-трассировка) — в разделе [Локальная отладка фильтров](./logstash_pipelines.md#локальная-отладка-фильтров).

## Типичные проблемы и их решение (Troubleshooting)

| Тег / симптом | Причина | Действие |
| :--- | :--- | :--- |
| `_mutate_error` | Сбой операции внутри блока mutate (например, `gsub` по не-строке); **остальные операции блока прерваны** | Вынести сбойную операцию в отдельный блок, проверить типы полей |
| `_jsonparsefailure` | Поле `source` не является валидным JSON | Для намеренно смешанного потока — `skip_on_invalid_json => true`; иначе разбирать источник или маршрутизировать на ручной разбор |
| `_timestampparsefailure`, поле `_@timestamp` | `@timestamp` из JSON не распознан как время | Исправить формат на стороне источника или разобрать поле явным `date` |
| `_kv_filter_error` / `_kv_filter_timeout` | Исключение разбора либо превышение `timeout_millis` (30 с) на патологической строке | Упростить разбор, сузить `source`, использовать `include_keys` |
| Колонки `column1`… вместо имён | Не задан `columns` и/или нет заголовка | Задать `columns`; для заголовка — `autodetect_column_names` **и** `pipeline.workers => 1` |
| Предупреждение ECS «target isn't set» (json/kv/csv/elasticsearch/geoip) | Режим ECS включён, а `target` не задан | Задать `target` явно — иначе возможен конфликт со схемой |
| `_geoip_lookup_failure` | Адрес не найден в базе, приватный/некорректный IP | Норма для приватных диапазонов; для публичных — проверить поле `source` |
| `_geoip_expired_database` | 30 дней без обновления EULA-базы — обогащение остановлено | Разрешить автообновление или настроить свой эндпоинт/прокси |
| Обогащение geoip «молча» не происходит (без тега) | City-база не вернула пару lat/lon | Проверить базу/адрес; ASN-база не зависит от координат |
| `_elasticsearch_lookup_failure` | Нет доступа к кластеру/индексу, невалидный запрос | Проверить `hosts`/аутентификацию и права `read` + `monitoring`, сузить `index` |
| `_syslogpriparsefailure` | Код facility вне известных меток (`use_labels => true`) | Проверить формат PRI в источнике; дополнить `facility_labels` или отключить `use_labels` |
| `_urldecodefailure` | Исключение при декодировании (несоответствие `charset` источнику) | Указать верный `charset`; вместо `all_fields` ограничить `field` |
| `cidr` не срабатывает (тега нет) | Адрес не попал ни в одну сеть либо задано не то поле (`address`/`address_field`) | Проверить поле IP и формат сетей; промах CIDR-фильтра — норма, тег не ставится |

## Лучшие практики

* В ECS-окружении всегда задавайте `target` у json/kv/csv/geoip/elasticsearch — это и требование схемы, и страховка от затирания полей (существующий `target` перезаписывается).
* Дорогие фильтры (`geoip`, `elasticsearch`) вызывайте только внутри ветки условия — до них, а не после.
* Операции mutate, где важна последовательность, разделяйте по блокам; порядок внутри одного блока задан плагином и не редактируется.
* После успешного разбора удаляйте сырые/вспомогательные поля через `remove_field` в том же блоке — и не удаляйте их раньше, чем убедились в качестве парсинга (иначе DLQ-перечитывание останется без исходных данных).
* Для elasticsearch-фильтра: узкий `index`, `result_size => 1`, сортировка по `@timestamp:desc` («последнее событие») и ветка условия только на релевантных событиях.
* Мониторьте состояние GeoIP-баз (`geoip_download_manager`) наравне с очередями: истёкшая база — это тихая потеря обогащения.
* Приводите типы (`convert`) сразу после разбора — числовые поля корректно работают в условиях и в сортировке Elasticsearch.
* Для UA-разбора выбирайте место по нагрузке: если событие всё равно проходит через Elasticsearch, дешевле оставить разбор процессору `user_agent` в ingest pipeline; фильтр `useragent` оправдан, когда обогащение нужно до отправки в кластер или результат кладётся в отдельное поле.
* Списки сетей для `cidr` держите в `network_path` и обновляйте файл — это воспроизводимее, чем литералы в pipeline, и не требует перезапуска для периодической перечитки.

## Дополнительная информация

### См. также

* **[Logstash: Обзор](./logstash_overview.md)** — предварительные требования, установка и управление плагинами (`logstash-plugin`), конфигурация и запуск.
* **[Logstash: Условные операторы и sprintf](./logstash-conditionals.md)** — синтаксис `if`/`else`, операторы `in`, подстановка `%{...}`.
* **[Logstash: Конвейеры, фильтры и производительность](./logstash_pipelines.md)** — порядок фильтров в конвейере, date/translate/split/clone/throttle/fingerprint, отладка, flow-метрики.
* **[Logstash: Входы, выходы и маршрутизация](./logstash_inputs_outputs.md)** — фильтры-спутники входов/выходов, условная маршрутизация.
* **[Grok и Dissect Patterns](../grok_dissect_patterns.md)** — парсинг нерегулярных строк (комплементарен `kv`/`csv`).
* **[Ingest Pipelines](../Elasticsearch/elasticsearch_ingest_pipelines.md)** — обогащение (в том числе GeoIP) на стороне Elasticsearch.
* **[mutate (Официально)](https://www.elastic.co/docs/reference/logstash/plugins/plugins-filters-mutate)** — первоисточник опций и порядка операций.
* **[json (Официально)](https://www.elastic.co/docs/reference/logstash/plugins/plugins-filters-json)**, **[kv (Официально)](https://www.elastic.co/docs/reference/logstash/plugins/plugins-filters-kv)**, **[csv (Официально)](https://www.elastic.co/docs/reference/logstash/plugins/plugins-filters-csv)** — справочники парсящих фильтров.
* **[elasticsearch filter (Официально)](https://www.elastic.co/docs/reference/logstash/plugins/plugins-filters-elasticsearch)**, **[geoip filter (Официально)](https://www.elastic.co/docs/reference/logstash/plugins/plugins-filters-geoip)** — первоисточники фильтров обогащения.
* **[useragent (Официально)](https://www.elastic.co/docs/reference/logstash/plugins/plugins-filters-useragent)**, **[cidr (Официально)](https://www.elastic.co/docs/reference/logstash/plugins/plugins-filters-cidr)**, **[syslog_pri (Официально)](https://www.elastic.co/docs/reference/logstash/plugins/plugins-filters-syslog_pri)**, **[urldecode (Официально)](https://www.elastic.co/docs/reference/logstash/plugins/plugins-filters-urldecode)** — справочники фильтров-спутников.
