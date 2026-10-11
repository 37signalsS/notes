# Logstash: Входы, выходы и маршрутизация

**Актуально для:** Logstash 8.19 (LTS) / 9.5.x

> Эта заметка — практический справочник по стадиям Input и Output: конфигурации входных и выходных плагинов, маршрутизация событий между ними, семантика повторных попыток (retry) и обработка многострочных сообщений. Базовые понятия стадий — в [общем обзоре Logstash](./logstash_overview.md#стадии-обработки-данных), архитектура конвейеров и фильтры — в [заметке о конвейерах](./logstash_pipelines.md).

## Определения

* **Input (Вход)** — плагин, получающий события из внешнего источника (файл, сокет, очередь, API) и помещающий их в очередь конвейера. Источник может блокироваться: при заполненной очереди (backpressure) input приостанавливает чтение, а не теряет данные.
* **Output (Выход)** — плагин, доставляющий события в целевую систему. Событие считается обработанным только после успешного вывода; до этого момента оно подтверждается (ACK) очереди лишь после записи в неё — так реализуется at-least-once семантика с включенной Persistent Queue.
* **Retry (Повторные попытки)** — механизм повторной отправки неудавшихся bulk-запросов. Семантика retry у каждого output-плагина своя и разобрана ниже — это один из главных источников потери данных «по неосторожности».
* **Routing (Маршрутизация)** — выбор выхода для события по условиям `if`/`else if`/`else` в секции `output` (или `filter`). Позволяет писать один поток в несколько индексов/систем без дублирования входа.
* **Codec (Кодек)** — плагин на границе стадии: превращает поток байтов в события (входы) и события в поток (выходы). Без кодека бинарный вход `tcp` выдал бы одно мусорное событие на весь поток; `multiline` — кодек, склеивающий многострочные записи (стектрейсы) в одно событие.
* **`@metadata`** — служебная область события, не доходит до output-плагинов (не пишется в Elasticsearch). Используется для передачи служебных значений между стадиями, например для выбора индекса.
* **Backpressure (обратное давление)** — механизм, при котором input приостанавливает чтение, когда конвейер не успевает обрабатывать события (очередь заполнена, воркеры заняты). Плагины, поддерживающие backpressure, не теряют данные — они читают «столько, сколько могут обработать».
* **Sincedb** — файл состояния плагина `file`, хранящий позицию чтения (inode, offset) для каждого отслеживаемого файла. Позволяет продолжать чтение после перезапуска Logstash без дубликатов и пропусков.
* **Persistent Queue (PQ)** — дисковая очередь событий (`queue.type: persisted`), сохраняющая события между перезапусками и обеспечивающая устойчивость к сбоям.
* **Dead Letter Queue (DLQ)** — очередь событий, которые не удалось обработать/вывести (ошибки маппинга, превышение лимитов). Включается `dead_letter_queue.enable: true`.

## Предпосылки и предварительная настройка (Prerequisites)

Перед настройкой входов/выходов проверьте:

1. **`queue.type: persisted` для production.** Memory-очередь не защищает от потерь при сбоях конвейера и не поддерживает zero-downtime reload. Дисковая очередь сохраняет события между перезапусками и переключениями конвейеров.
2. **Достаточно места под `path.data`.** Для PQ и sincedb-файлов (file input) требуется дисковое пространство. При hot-reload PQ не очищается — старые данные остаются до обработки новым конвейером.
3. **Конфигурация валидна перед деплоем.** Прогоните `logstash -t` после каждой правки входов/выходов. Невалидная конфигурация остановит конвейер при старте.
4. **Секреты — только через Keystore.** Пароли в `.conf`-файлах — уязвимость. Используйте `${VAR}`-подстановку из `logstash.keystore` (см. [Keystore в обзоре](./logstash_overview.md#настройка-секретов-через-keystore)).
5. **Порты свободны.** Каждый вход слушает свой порт (beats — 5044, syslog — 514, http — 8080). Проверьте `ss -tlnp` перед запуском — конфликт портов остановит Logstash с ошибкой.
6. **Конфигурация хранится в `.conf`-файлах.** Inline-конфигурация через `-e` не поддерживает `config.reload.automatic` и не подходит для production-конвейеров.
7. **Один вход — одна ответственность.** Разные типы данных (syslog, webhooks, kafka) — разные конвейеры в `pipelines.yml`, чтобы отказ одного источника не блокировал остальные.

## Основные концепции

### Выбор входа

| Источник данных | Вход | Ключевые особенности |
| :--- | :--- | :--- |
| Filebeat / Elastic Agent | `beats` | Бинарный протокол Beats, порт 5044; TLS — см. [сетевые требования](../elasticsearch_network_requirements.md#logstash-beats-input-с-tls) |
| Syslog-сервер (RFC3164) | `syslog` | Порт 514, слушает TCP и UDP одновременно; TLS **не поддерживает** |
| Гибкий TCP/UDP-поток | `tcp` / `udp` | Свой кодек, поддержка TLS у `tcp` (вход `ssl_enabled`) |
| HTTP-коллектор (webhooks) | `http` | HTTP POST на порту 8080, JSON по умолчанию |
| Очередь сообщений | `kafka` | Consumer group, несколько потоков чтения, библиотека Kafka Client 4.2.0 |
| Реляционная БД | `jdbc` | Периодический SQL по cron-расписанию, инкрементальные выборки |
| Локальные логи | `file` | Sincedb (положение), `mode: tail|read`, `start_position`, `ignore_older` |
| Опрос HTTP API | `http_poller` | Периодические GET/POST запросы к REST API, планировщик cron/every |
| Генератор тестовых событий | `generator` | Синтетические события по расписанию; для тестов производительности и health-check |
| Объектное хранилище | `s3` | Чтение объектов из S3-совместимых хранилищ (MinIO, AWS S3), поддержка SQS-уведомлений |
| DLQ / stdin (отладка) | `dead_letter_queue`, `stdin` | Перечитывание ошибочных событий; быстрый локальный тест |

Общий принцип: вход отвечает **только** за приём и постановку в очередь; нормализация — задача фильтров, выбор назначения — output. Держите один вход на конвейер там, где это возможно: так проще масштабировать и изолировать отказы (см. [pipeline-to-pipeline](./logstash_pipelines.md#использование-pipeline-to-pipeline-с-изоляцией-агрегации)).

### Маршрутизация в output

Условия в секции `output` работают так же, как в `filter`. Семантика веток (взаимоисключительная цепочка `if/else if/else` против независимых `if`, поведение при отсутствии совпадений) и полные примеры цепочек — в [Условные операторы и sprintf](./logstash-conditionals.md#практические-сценарии).

Практические паттерны:

* **Выбор индекса через `[@metadata]`** — вычислите имя индекса в `filter` (туда `@metadata` попадает, в Elasticsearch — нет) и подставьте его в `index`; полный пример с ветвлением — [Условные операторы и sprintf](./logstash-conditionals.md#вложенные-условия-и-metadata-как-промежуточный-флаг).
* **Дублирование потока** (один вход → две системы, например Elasticsearch и Kafka) — просто перечислите оба выхода без условий: оба получат копию каждого события.
* **Динамический выбор через `pipeline` output** — пересылка в другой конвейер по адресу, если обработка должна идти с другими воркерами/очередью (подробно — [P2P в заметке о конвейерах](./logstash_pipelines.md#использование-pipeline-to-pipeline-с-изоляцией-агрегации)).

При нескольких `elasticsearch`-выходах помните: каждый выход — отдельный клиент с собственным connection pool; для минимизации открытых соединений и максимизации размера bulk предпочтительнее **один** выход с динамическим `index`, а не несколько статических.

### Семантика retry в elasticsearch output

Retry-политика плагина (изменена в 8.1.1) устроена двумя уровнями:

1. **Уровень HTTP-запроса к bulk API.** Ожидается код 200; все остальные (включая 413 Payload Too Large) ретраятся **бесконечно**, пока не добьются успеха. Исключение — если перенаправить код в DLQ: `dlq_custom_codes => [413]` (события с oversized-запросом уходят в DLQ вместо бесконечных повторов).
2. **Уровень отдельного документа в ответе bulk:**

| Код | Поведение |
| :--- | :--- |
| 400, 404 (ошибка маппинга) | В DLQ (если включен); без DLQ — лог + **дроп события** |
| 409 (conflict) | Warning в лог + **дроп** (не ретраится; для update используйте `retry_on_conflict`, по умолчанию `1`) |
| Прочие документ-ошибки | Ретраятся бесконечно, пока не исправятся; точечное исключение — `drop_error_types => [...]` (дроп без записи в DLQ) |

Интервал между bulk-ретраями — экспоненциальный: `retry_initial_interval` (по умолчанию 2 с) удваивается до `retry_max_interval` (64 с). Таймаут сетевых операций — `timeout` (60 с), по его истечении запрос ретраится. События, попавшие в DLQ, разбираются отдельно — процедура перечитывания описана [в заметке о конвейерах](./logstash_pipelines.md#управление-dead-letter-queue).

Ключевой вывод для production: **события не теряются молча** — сетевые отказы и ошибки маппинга либо ретраятся, либо складываются в DLQ; теряются только те события, что отброшены по явной политике (409, `drop_error_types`, переполнение DLQ). Включайте `dead_letter_queue.enable: true` и мониторьте её объем.

### Кодеки и кодировки

Кодек задается опцией `codec` у входа/выхода и определяет, как превращать поток байтов в события и обратно. Кодировка (charset) отвечает за перевод байтов в символы и задается той же опцией у плагина.

| Кодек | Роль | Ключевые особенности |
| :--- | :--- | :--- |
| `plain` | Строка целиком в поле `message` | Кодек по умолчанию там, где не задан другой; `charset` (по умолчанию `UTF-8`); в режиме кодирования поддерживает шаблон `format` (sprintf-подстановка полей события) |
| `json` | Разбор JSON-строки в поля события | Опции `charset`, `target`; JSON-массив разворачивается в **несколько** событий; невалидный JSON не теряется — строка уходит в `message` нового события с тегом `_jsonparsefailure` |
| `line` | Событие на каждую завершенную строку | `delimiter` (по умолчанию `"\n"`); при декодировании **буферизует неполные строки** и выпускает событие только при появлении разделителя; при кодировании дописывает `delimiter` в конец |
| `multiline` | Склейка нескольких строк в одно событие | См. следующий раздел |
| `rubydebug` | Читаемый дамп события в stdout | Для отладки; `metadata => true` — показывать служебные поля `@metadata` |

Кодировки: `charset` принимает имена charset'ов Java; на практике встречаются `UTF-8` (по умолчанию) и `ISO-8859-1`/`windows-1251` для старых логов с не-UTF-8 байтами. Если поток приходит в неверной кодировке, исправлять её нужно **здесь** — фильтры уже видят битые строки. Разбор содержимого (JSON, key=value, CSV) — задача фильтров, а не кодеков: кодек `json` удобен, когда вход — чистый JSON-поток (например `tcp` с `codec => json`), для смешанных потоков смотрите [фильтр json](./logstash-filter-plugins.md#фильтр-json--разбор-json).

### Многострочные сообщения: multiline codec

Кодек `multiline` объединяет несколько строк входного потока в одно событие — классический случай стектрейсов в логах приложений:

```ruby
input {
  tcp {
    port => 5514
    codec => multiline {
      pattern => "^\s"          # строка, начинающаяся с пробела — продолжение
      what => "previous"        # присоединять к предыдущей строке
      negate => false           # true = матчинг означает «новая запись»
      max_lines => 500          # предохранительный потолок склейки
      max_bytes => "10MiB"      # лимит размера одного склеенного события
    }
  }
}
```

Опции: `pattern` и `what` обязательны; `what => "next"` (вместе с `negate => true`) — зеркальный режим, когда маркерной является сама первая строка; `multiline_tag` (по умолчанию `multiline`) — тег добавляемого события; `auto_flush_interval` — периодический сброс буфера (защита от «зависших» незакрытых записей); `charset`, `patterns_dir` — кодировка и каталог с доп. паттернами. Событие не должно превышать `max_bytes` — иначе оно режется и получает тег, а стектрейс распадется.

Важно: не используйте `multiline` в `beats`-входе, к которому подключено несколько хостов — потоки разных хостов смешиваются в одном буфере и склейка ломается. Многострочность на стороне агента — забота Filebeat (`multiline`-парсер, см. [Filebeat](../filebeat_overview.md)); в Logstash кодек нужен для потоков, которые приходят сырыми (tcp/udp/files).

### Фильтры-спутники входов и выходов

Ниже — фильтры, которые чаще всего применяются непосредственно рядом с приёмом/отправкой; полный обзор фильтров — в [заметке о конвейерах](./logstash_pipelines.md).

* **`date`** — устанавливает `@timestamp` из распарсенного поля, иначе событие получит время прихода в Logstash (ошибка для исторических данных). `match => ["поле", "формат"]` (литералы `ISO8601`, `UNIX`, `UNIX_MS`, `TAI64N`); неудача — тег `_dateparsefailure`; `target` (по умолчанию `@timestamp`), `timezone`/`locale`, `precision => "ns"` для наносекунд (в этом режиме парсинг идет через `java.time` вместо joda-time). Семантика временных полей и работа с запоздавшими событиями — в [Логи: временные метки и запоздавшие события](../log-timestamps-and-late-events.md).
* **`translate`** — обогащение по словарю: `source` (обязателен) → `target` (по умолчанию `translation`); словарь задается хэшем `dictionary` **или** файлом `dictionary_path` (YAML/JSON/CSV, одновременно — ошибка); `fallback` при отсутствии совпадения; `refresh_interval` (300 с) — период перечитывания файла; поддерживает `regex => true` и обработку массивов через `iterate_on`.
* **`split`** — разбиение одного события на несколько по разделителю (по умолчанию поле `message`, `terminator` `"\n"`): удобно превращать вывод команды или JSON-массив в отдельные события. Учтите: фильтр расширяет батч — с 9.4.1 Logstash автоматически дробит разросшиеся батчи обратно до `pipeline.batch.size` перед output.
* **`clone`** — дублирование события (`clones => ["имя1", "имя2"]`); копия получает метку в `type` (ECS выключен) или в `tags` (ECS включен) и обрабатывается дальше с места создания фильтра. Используется для разведения потоков (например, один события в архив, второй — в реалтайм-алертинг).
* **`throttle`** — ограничение числа событий по ключу за период: `key` (обязателен, например `%{host}`), `period` (60 с), `before_count`/`after_count` (границы, `-1` — не ограничивать), `max_age` (3600 с — время жизни таймслота, рекомендуется ≥ 2×`period`). Отсеченные события помечаются `add_tag => ["throttled"]` — дальше их обычно дропает `drop {}` или пропускает мимо алертинга.
* **`fingerprint`** — детерминированный хэш полей события (`method` обязателен: `SHA1` по умолчанию, также `SHA256`/`MD5`/`MURMUR3`/`UUID`/`IPV4_NETWORK`), результат в `fingerprint` (ECS — `[event][hash]`). Классическое применение — генерация стабильного `document_id` для Elasticsearch, чтобы повторная доставка обновляла документ, а не создавала дубликат; разбор семантики дедупликации (в т.ч. различие data stream / обычный индекс) — в [Семантика доставки и дедупликация](../log-delivery-and-deduplication.md).

## Практические сценарии

### Прием от Filebeat / Elastic Agent (beats)

```ruby
input {
  beats {
    port => 5044
    # TLS-вариант — в разделе «Logstash: Beats input с TLS»
    # https://www.elastic.co/docs/reference/logstash/plugins/plugins-inputs-beats
  }
}
```

Плагин принимает уже декодированные события (кодек не нужен), сам управляет сжатием и TLS-опциями. Подключение агента и TLS-конфигурация — в [сетевых требованиях](../elasticsearch_network_requirements.md#logstash-beats-input-с-tls).

### Syslog-сервер

```ruby
input {
  syslog {
    port => 514           # слушает TCP и UDP одновременно
    host => "0.0.0.0"
    # grok_pattern по умолчанию: <%{POSINT:priority}>%{SYSLOGLINE} (RFC3164)
  }
}
```

Плагин разбирает классический syslog RFC3164 сам (priority, host, program). Для RFC5424 и для TLS шифрованный syslog используйте `tcp` с нужным кодеком — `syslog`-плагин опций шифрования не имеет. Ограничение `udp`: буфер датаграммы по умолчанию 65536 байт (`buffer_size`), очередь на 200 датаграмм (`queue_size`) — при переполнении **новые датаграммы отбрасываются** (потери на UDP неизбежны в принципе).

### TCP/UDP вход с кодеком

```ruby
input {
  tcp {
    port => 5514
    host => "0.0.0.0"
    codec => json                    # или line / multiline
    mode => "server"                 # server (слушать) | client (подключаться)
    tcp_keep_alive => true
    # Для защищенного приема (например syslog-over-TLS):
    # ssl_enabled => true
    # ssl_certificate => "/etc/pki/logstash/logstash.crt"
    # ssl_key => "/etc/pki/logstash/logstash.pk8"
    # ssl_client_authentication => "required"   # none | optional | required
    # ssl_verification_mode => "full"           # full | none
  }
}
input {
  udp {
    port => 5514
    buffer_size => 65536             # размер буфера на датаграмму
    workers => 2                     # потоки чтения сокета
  }
}
```

`ssl_certificate_authorities` добавляется при взаимной аутентификации; полный TLS-пример — в [сетевых требованиях](../elasticsearch_network_requirements.md#logstash-syslog-over-tls-tcp-input). У `udp` есть `source_ip_fieldname` — куда писать IP отправителя, полезно для обогащения геолокацией.

### HTTP-вход (webhooks, микросервисы)

```ruby
input {
  http {
    port => 8080
    host => "0.0.0.0"
    user => "collector"              # basic auth (с паролем ниже)
    password => "${HTTP_INPUT_PASS}" # значение из Keystore
    # ssl_enabled => true
    # ssl_certificate => "/etc/pki/logstash/logstash.crt"
    # ssl_key => "/etc/pki/logstash/logstash.pk8"
    additional_codecs => { "application/json" => "json" }  # по умолчанию
    max_content_length => 104857600  # 100 MiB на запрос
    max_pending_requests => 200      # при переполнении — HTTP 429
  }
}
```

Отправитель получает `202 Accepted`, когда событие принято в конвейер (не когда записано в Elasticsearch). Проверка:

```bash
curl -u collector -H 'Content-Type: application/json' \
  -d '{"level":"INFO","service":"web","message":"hello"}' http://localhost:8080/
# → 202 Accepted
```

### Чтение из Kafka

```ruby
input {
  kafka {
    bootstrap_servers => "kafka-1:9092,kafka-2:9092"
    topics => ["app-logs"]
    group_id => "logstash-app-logs"   # уникален на каждый вход в конвейере
    consumer_threads => 4             # <= число партиций топика
    decorate_events => "basic"        # none | basic | extended
    # auto_offset_reset => "earliest" # куда идти без сохраненного offset
    # security_protocol => "SASL_SSL" # + sasl_mechanism, sasl_jaas_config и т.д.
  }
}
```

Как это работает: несколько экземпляров Logstash с одинаковым `group_id` образуют один consumer group — партиции делятся между ними, каждая доставляется ровно одному потребителю; `consumer_threads` — число потоков внутри одного процесса (идеально — не больше числа партиций, иначе потоки простаивают). Метаданные сообщения (topic, partition, offset, key, timestamp) попадают в `[@metadata][kafka][...]` только при `decorate_events => basic|extended`; чтобы они дошли до Elasticsearch, скопируйте их в событие `mutate`. Offset коммитится автоматически (`enable_auto_commit => true`, интервал 5000 мс); с `enable_auto_commit => false` сдвиг продвигается после записи события в очередь конвейера.

### Периодический импорт из БД (jdbc)

```ruby
input {
  jdbc {
    jdbc_connection_string => "jdbc:postgresql://db:5432/app"
    jdbc_driver_class => "org.postgresql.Driver"
    jdbc_driver_library => "/usr/share/logstash/postgresql.jar"  # драйвер НЕ в комплекте
    jdbc_user => "logstash_ro"
    password => "${DB_PASSWORD}"
    schedule => "*/5 * * * *"        # cron: каждые 5 минут
    statement => "SELECT id, created_at, payload FROM events WHERE created_at > :sql_last_value"
    use_column_value => true
    tracking_column => "created_at"
    tracking_column_type => "timestamp"
    last_run_metadata_path => "/var/lib/logstash/jdbc_last_run"  # состояние между запусками
    jdbc_paging_enabled => true      # постраничная выборка (по умолчанию выключен)
    jdbc_page_size => 100000
  }
}
```

Инкрементальный импорт строится на `:sql_last_value` — плагин подставляет туда последнее сохраненное значение `tracking_column` и запоминает новое в `last_run_metadata_path` (файл, а не БД — следите за его наличием при redeploy). Для полноэкстраторных загрузок оставьте `use_column_value => false` и читайте все строки каждый цикл. Опции `clean_run` (игнорировать сохраненное состояние) и `jdbc_validate_connection` (проверять соединение перед запросом) полезны при отладке.

### Чтение локальных файлов (file)

```ruby
input {
  file {
    path => ["/var/log/app/*.log", "/var/log/nginx/access.log"]
    start_position => "beginning"    # beginning | end
    mode => "tail"                   # tail | read (read — разовый проход, tail — слежение)
    sincedb_path => "/var/lib/logstash/sincedb_app"
    sincedb_write_interval => 15     # сек, сброс sincedb на диск
    ignore_older => 86400            # игнорировать файлы, не обновляемые > 24ч
    close_older => 3600              # закрывать дескриптор, если файл не обновлялся > 1ч
    stat_interval => 10              # интервал проверки новых файлов/изменений (сек)
    delimiter => "
"                # разделитель строк
    codec => "json"                  # или line / multiline
  }
}
```

Плагин использует **sincedb** (файл состояния) для запоминания позиции чтения (inode + offset). При перезапуске Logstash продолжает с того места — нет дублей и потерь.
* `start_position => "beginning"` — читать файл с начала (только при первом запуске, если sincedb пуст); `"end"` — только новые строки.
* `mode => "tail"` — следит за добавлением строк (как `tail -f`); `"read"` — читает файл один раз и закрывает (для батч-загрузок).
* `ignore_older` / `close_older` — защита от утечки файловых дескрипторов при большом числе файлов.
* Для ротируемых логов (logrotate) убедитесь, что `sincedb_path` на персистентном томе, иначе после ротации/перезапуска позиция потеряется.

### Опрос HTTP API (http_poller)

```ruby
input {
  http_poller {
    urls => {
      health => {
        method => "get"
        url => "https://api.example.com/health"
        headers => { "Authorization" => "Bearer ${API_TOKEN}" }
      }
      metrics => {
        method => "post"
        url => "https://api.example.com/metrics"
        body => '{"query": "up"}'
      }
    }
    request_timeout => 30
    schedule => { cron => "*/5 * * * * UTC" }   # или every => "30s"
    codec => "json"
    metadata_target => "http_poller_metadata"   # статус-код, url, response time в @metadata
  }
}
```

Плагин опрашивает HTTP-эндпоинты по расписанию (`cron` или `every`). Каждый URL в `urls` может иметь свой метод, заголовки, тело. Полезен для:
* Health-check'ов микросервисов (превращать HTTP-статус в события для алертинга)
* Сбора метрик с `/metrics` эндпоинтов (Prometheus-формат разбирается фильтром `json` + `kv`)
* Интеграции с REST API, не поддерживающими webhook

Ограничения: не поддерживает streaming/SSE; при большом числе URL лучше разнести по нескольким входам.

### Генератор тестовых событий (generator)

```ruby
input {
  generator {
    message => '{"service":"test","level":"INFO","msg":"synthetic event"}'
    codec => "json"
    count => 1000              # всего событий (0 = бесконечно)
    lines_per_second => 100    # rate limiting
    threads => 1
  }
}
```

Для нагрузочного тестирования конвейеров, проверки throughput, валидации фильтров/выходов без внешних зависимостей. `count => 0` + `lines_per_second` — бесконечный поток с заданным RPS.

### Чтение из S3-совместимых хранилищ (s3)

```ruby
input {
  s3 {
    bucket => "app-logs"
    region => "us-east-1"
    access_key_id => "${S3_ACCESS_KEY}"
    secret_access_key => "${S3_SECRET_KEY}"
    endpoint => "https://minio.internal:9000"  # для MinIO / S3-совместимых
    prefix => "logs/2024/"
    additional_settings => {
      force_path_style => true
      follow_redirects => false
    }
    sincedb_path => "/var/lib/logstash/sincedb_s3"
    delete => false                # true = удалять объект после успешного чтения
    codec => "json"
  }
}
```

Читает объекты из бакета (поддерживает MinIO, AWS S3, Ceph RGW). Использует sincedb для отслеживания обработанных объектов. Может получать уведомления через SQS (`queue_url`, `queue_region`) для near-real-time обработки вместо поллинга.

### Вывод в Kafka

```ruby
output {
  kafka {
    topic_id => "normalized-logs"    # единственная обязательная опция
    codec => json                    # по умолчанию plain (строка с timestamp/hostname)
    bootstrap_servers => "kafka-1:9092,kafka-2:9092"
    acks => "all"                    # 0 | 1 | all (по умолчанию "1")
    compression_type => "gzip"       # none | gzip | snappy | lz4 | zstd
    message_key => "%{[host][hostname]}"  # ключ партиционирования
    # retries — по умолчанию бесконечные; менять не рекомендуется (риск потерь)
  }
}
```

Гарантии: `acks => "all"` — лидер подтверждает запись после репликации во все in-sync реплики; `acks => "0"` — подтверждения нет, потери возможны даже без сбоя. С 10.5.0 плагин ретраит только `RetriableException`/`InterruptException`, прочие ошибки логируются и **сообщение отбрасывается** (раньше любая ошибка ретраилась бесконечно и могла зависить конвейер). Отдельная ловушка — таймстемпы: Logstash пишет `@timestamp` события, поэтому событие недельной давности может быть отброшено брокером при retention меньше возраста события (настройка `log.message.timestamp.type`); для сырых потоков рассмотрите `LogAppendTime` на стороне брокера.

### Вывод в HTTP (http)

```ruby
output {
  http {
    url => "https://webhook.example.com/ingest"
    http_method => "post"
    format => "json"
    content_type => "application/json"
    headers => { "Authorization" => "Bearer ${WEBHOOK_TOKEN}" }
    retry_non_idempotent => true
    retry_options => {
      max_retries => 3
      retry_wait => 5
    }
    pool_max => 50
    connect_timeout => 10
    request_timeout => 60
  }
}
```

Доставляет события на HTTP-эндпоинт (webhook, API). Поддерживает батчинг (собирает события в массив до `pool_max` или таймаута). `retry_non_idempotent => true` позволяет ретраить POST (по умолчанию ретраится только idempotent методы). Важно: выход считает событие успешно доставленным при 2xx; 4xx/5xx — ретрай по политике выше, затем — дроп или DLQ (если настроен). Для высокой нагрузки — включите Persistent Queue и следите за `events.out` lag.

### Вывод в файл (file)

```ruby
output {
  file {
    path => "/var/log/logstash/%{{yyyy-MM-dd}}/app-%{[host][hostname]}.log"
    codec => "json_lines"
    gzip => false
    flush_interval => 2              # сек, сброс буфера на диск
    file_create_mode => "0644"
    dir_create_mode => "0755"
  }
}
```

Пишет события в файлы с ротацией по времени (sprintf в `path`). `codec => "json_lines"` — по одной JSON-строке на событие. `flush_interval` — как часто сбрасывать OS-буфер (0 = каждый event, дорого). Для архивации «сырых» логов перед парсингом или холодного хранения. Не заменяет logrotate — управляйте ротацией внешне.

### Вывод в stdout (stdout)

```ruby
output {
  stdout {
    codec => "rubydebug"   # или json_lines / plain
  }
}
```

Для отладки, разработки конвейеров, тестирования в CI. В production не используется — производительность печати в терминал низкая, нет буферизации, блокирует воркеры.

### Вывод в S3 (s3)

```ruby
output {
  s3 {
    bucket => "logstash-archive"
    region => "us-east-1"
    access_key_id => "${S3_ACCESS_KEY}"
    secret_access_key => "${S3_SECRET_KEY}"
    endpoint => "https://minio.internal:9000"
    prefix => "logs/%{{yyyy/MM/dd}}/"
    size_file => 52428800          # 50 MiB на файл
    time_file => 300               # 5 мин — макс. время открытого файла
    codec => "json_lines"
    canned_acl => "private"
    server_side_encryption => "AES256"
    temporary_directory => "/tmp/logstash-s3"
    restore => false               # true = не удалять временные файлы после загрузки
  }
}
```

Архивирует события в S3/MinIO с ротацией по размеру (`size_file`) и времени (`time_file`). Собирает события во временные файлы в `temporary_directory`, затем загружает multipart'ом. Для cold storage / compliance. Требует достаточно места в `temporary_directory` под накопление батчей.

### Вывод в Elasticsearch: надежность и объем

```ruby
output {
  elasticsearch {
    hosts => ["https://es-1:9200", "https://es-2:9200"]  # только data/client-ноды
    user => "logstash_writer"
    password => "${ES_PASSWORD}"      # или api_key => "${ES_API_KEY}"
    index => "logs-generic-default"   # либо data_stream => "true"
    compression_level => 1            # 0-9; gzip включен с 1-го уровня
    retry_initial_interval => 2       # старт retry (с), дальше x2
    retry_max_interval => 64          # потолок интервала retry (с)
    # manage_template => false        # если шаблоны индексов накатывает CI
  }
}
```

Ключевые факты эксплуатации:

* **Bulk-батчи:** запросы дробятся, если батч превышает 20 МБ; один документ больше 20 МБ уходит отдельным запросом. Мелкие bulk-запросы раздувают очередь — отсюда рекомендация крупных `pipeline.batch.size` ([тюнинг](./logstash_pipelines.md#оптимизация-и-тюнинг-logstash-9x)).
* **Сжатие:** по умолчанию bulk-запросы сжимаются gzip (уровень 1); `compression_level` 0 отключает, 9 — максимум сжатия ценой CPU.
* **Хосты:** в `hosts` не должны попадать выделенные master-ноды — bulk шлется только data/client-нодам.
* **ILM и шаблоны:** `ilm_enabled => "auto"` (по умолчанию) включает index lifecycle management, если кластер это поддерживает; `manage_template => true` накатывает шаблон при старте — отключите, если управление шаблонами centralized (IaC).
* **Data streams:** `data_stream => "auto"` (дефолт с 8.0) при включенном ECS-режиме пишет в data streams `<type>-<dataset>-<namespace>` — правильный выбор для логов.

## Операции и команды (Operations and Commands)

### Валидация и тестирование конфигурации

```bash
# Проверка синтаксиса конфигурации (обязательно перед деплоем)
logstash -t --config.string 'input { stdin {} } output { stdout {} }'
# или для файла конфигурации
logstash -t -f /etc/logstash/conf.d/pipeline.conf
# → Configuration OK

# Тестовый прогон с генератором событий
logstash -e 'input { generator { count => 10 codec => json } } output { stdout { codec => rubydebug } }'
# → 10 событий в stdout с полными полями

# Dry-run конвейера с реальными данными (stdin)
echo '{"message":"test","level":"INFO"}' | logstash -f /etc/logstash/conf.d/pipeline.conf
# → событие обработано через весь конвейер
```

### Управление плагинами

```bash
# Список установленных плагинов
logstash-plugin list
# → logstash-input-beats, logstash-filter-grok, logstash-output-elasticsearch, ...

# Поиск плагина
logstash-plugin list --verbose | grep -i kafka

# Установка плагина из RubyGems
logstash-plugin install logstash-input-http_poller
# → Installation successful

# Установка из локального .gem файла
logstash-plugin install /tmp/logstash-output-custom-1.0.0.gem

# Обновление плагина
logstash-plugin update logstash-input-beats

# Удаление плагина
logstash-plugin remove logstash-output-influxdb
```

### Мониторинг и диагностика через API

```bash
# Статистика конвейеров (events.in/out, queue, workers)
curl -s localhost:9600/_node/stats/pipelines | jq '.pipelines.main | {events: .events, queue: .queue, workers: .workers}'

# Подробная статистика входов/выходов конкретного конвейера
curl -s localhost:9600/_node/stats/pipelines | jq '.pipelines.main.plugins.inputs[] | {name: .name, events: .events}'
curl -s localhost:9600/_node/stats/pipelines | jq '.pipelines.main.plugins.outputs[] | {name: .name, events: .events, errors: .errors}'

# Статус Persistent Queue
curl -s localhost:9600/_node/stats/pipelines | jq '.pipelines.main.queue'

# Hot threads (CPU профиль)
curl -s localhost:9600/_node/hot_threads

# Информация о ноде (версия, JVM, GC)
curl -s localhost:9600/_node | jq '{version: .version, jvm: .jvm, gc: .gc}'

# Список конвейеров из pipelines.yml
curl -s localhost:9600/_node/pipelines | jq '.pipelines[] | {id: .id, status: .status, workers: .config.workers}'
```

### Управление sincedb (file input)

```bash
# Просмотр содержимого sincedb (требует logstash-stopped)
# sincedb — бинарный файл, читается через Ruby:
ruby -e 'require "sincedb"; db = Sincedb.new("/var/lib/logstash/sincedb_app"); db.each { |k,v| puts "#{k} => #{v}" }'

# Сброс позиции чтения (начать с начала)
rm /var/lib/logstash/sincedb_app
# Следующий запуск прочитает файлы с начала (если start_position => beginning)

# Резервное копирование sincedb перед обновлением
cp /var/lib/logstash/sincedb_app /backup/sincedb_app.$(date +%F)
```

### Управление Dead Letter Queue

```bash
# Проверка размера DLQ
du -sh /var/lib/logstash/dead_letter_queue/main/

# Перечитывание DLQ (требует остановленного конвейера)
logstash -f /etc/logstash/conf.d/dlq_replay.conf
# где dlq_replay.conf:
# input { dead_letter_queue { path => "/var/lib/logstash/dead_letter_queue" } }
# output { elasticsearch { ... } }

# Очистка DLQ после разбора
rm -rf /var/lib/logstash/dead_letter_queue/main/*
```

### Управление jdbc state

```bash
# Просмотр последнего значения tracking_column
cat /var/lib/logstash/jdbc_last_run
# → --- 2024-01-15 10:30:00.000000000 Z

# Сброс состояния (полная перезагрузка)
rm /var/lib/logstash/jdbc_last_run
# Или используйте clean_run => true в конфигурации
```

## Типичные проблемы и их решение (Troubleshooting)

1. **События не появляются в Elasticsearch, но `events.in` растет.**
   Диагностика: `curl -s localhost:9600/_node/stats/pipelines | jq '.pipelines.<id> | {events, flow}'` — если `out` отстает от `in` и растет очередь, смотрите output (доступность ES, ошибки маппинга в логе); если `in` не растет — проблема на входе (порт, агент, firewall: `ss -tlnp | grep <port>`).
2. **HTTP 413 в логе, конвейер крутит retry без конца.**
   Причина: bulk-запрос больше лимита кластера. Решение: снизить размер батча, либо `dlq_custom_codes => [413]`, чтобы такие события уходили в DLQ, а не ретраились бесконечно.
3. **События массово уходят в DLQ с 400/404.**
   Причина: конфликт маппинга (новое поле ломает шаблон индекса). Решение: исправить шаблон/ILM, затем перечитать DLQ input-плагином (`dead_letter_queue`) — процедура [здесь](./logstash_pipelines.md#управление-dead-letter-queue).
4. **Дубликаты документов в индексе при повторной доставке.**
   Причина: `document_id` не задан, каждая ретрая создает новый документ. Решение: задайте детерминированный id через `fingerprint`-фильтр (например, из хэша сообщения) или `document_id => "%{[@metadata][event_id]}"`.
5. **`_dateparsefailure` на части событий.**
   Причина: значение поля не соответствует ни одному формату в `match`. Решение: добавьте все реальные варианты формата в массив `match`, задайте `timezone`; события с тегом маршрутизируйте в отдельный индекс для разбора.
6. **Стектрейс разбит на много мелких событий.**
   Причина: многострочность не склеена — нет `multiline`-кодека (для сырых потоков) либо поток смешан из нескольких хостов в одном `beats`-входе. Решение: для tcp/udp — `codec => multiline` (см. выше); для агентов — multiline-парсер на стороне Filebeat; один хост на вход.
7. **UDP-вход «теряет» события под нагрузкой.**
   Причина: переполнение `queue_size` (200 датаграмм по умолчанию) — новые отбрасываются. Решение: увеличить `queue_size`/`buffer_size` и число `workers`; если потери недопустимы — переходите на TCP.
8. **Kafka-вход не читает все партиции.**
   Причина: `consumer_threads` меньше числа партиций либо несколько разных топиков читаются одним `group_id`. Решение: поднимите потоки до числа партиций, разнесите топики по разным входам с разными `group_id`.
9. **После перезапуска Logstash jdbc-импорт начинает заново.**
   Причина: утерян `last_run_metadata_path` (пересоздан контейнер без volume). Решение: вынесите файл на постоянный том и следите за его целостностью; для разовых прогонов — `clean_run`.

10. **`file` input не видит новые файлы / не читает ротированные логи.**
    Причина: `ignore_older` слишком мал, `stat_interval` слишком велик, или `sincedb_path` не на персистентном томе. Решение: увеличьте `ignore_older` (например, 86400), уменьшите `stat_interval` (10–30 сек), вынесите sincedb на volume. Для logrotate используйте `mode => "tail"` и не удаляйте sincedb.

11. **`http_poller` возвращает 429 / таймауты / не опрашивает все URL.**
    Причина: rate limiting на стороне API, `request_timeout` слишком мал, слишком много URL в одном входе. Решение: увеличьте `request_timeout`, добавьте `backoff` логику через фильтры, разнесите URL по нескольким `http_poller` входам с разными расписаниями.

12. **`generator` input не генерирует события / конвейер не запускается.**
    Причина: `count => 0` без `lines_per_second` (бесконечный поток без rate limit) может забить память; неверный `codec` для `message`. Решение: всегда задавайте `lines_per_second` при `count => 0`; проверяйте `codec => "json"` соответствует формату `message`.

13. **`s3` input не читает объекты / пропускает новые.**
    Причина: `prefix` не совпадает, нет прав доступа, SQS-уведомления не настроены, `sincedb_path` утерян. Решение: проверьте IAM/MinIO policy, настройте SQS для push-уведомлений, держите sincedb на персистентном томе.

14. **`http` output — события не доходят / получают 4xx/5xx.**
    Причина: неверный `url`, отсутствующие заголовки авторизации, тело не соответствует ожидаемому формату API, `retry_non_idempotent => false` для POST. Решение: тестируйте `curl` вручную, включите `retry_non_idempotent => true`, логируйте ответы через `response_format => "json"` (если поддерживается).

15. **`file` output — файлы не создаются / права доступа / диск переполнен.**
    Причина: нет прав на запись в `path`, родительская директория не существует, `flush_interval` слишком велик (данные в буфере), нет места на диске. Решение: проверьте `file_create_mode`/`dir_create_mode`, убедитесь в наличии места, уменьшите `flush_interval`, мониторьте диск.

16. **`s3` output — загрузка зависает / файлы не появляются в бакете.**
    Причина: `temporary_directory` переполнен, нет прав на multipart upload, `size_file`/`time_file` слишком малы (слишком много мелких файлов). Решение: увеличьте `temporary_directory` (отдельный том), проверьте IAM policy (`s3:PutObject`, `s3:AbortMultipartUpload`), увеличьте `size_file` до 50–100 MiB.

17. **`stdout` output блокирует конвейер / высокая задержка.**
    Причина: вывод в терминал синхронный и медленный; при высоком throughput воркеры блокируются на write(). Решение: в production не используйте `stdout`; для отладки — `codec => rubydebug` с `metadata => true`, ограничивайте `count` у generator.

## Лучшие практики и очистка окружения

* **Один вход — одна ответственность.** Разные типы данных (syslog, webhooks, kafka) — разные конвейеры в `pipelines.yml`, чтобы отказ одного источника не блокировал остальные.
* **Секреты — только через Keystore** (`password => "${ES_PASSWORD}"`), никаких паролей в `.conf` (см. [Keystore в обзоре](./logstash_overview.md#настройка-секретов-через-keystore)).
* **`-t` перед каждым рестартом** после правки конфигурации входа/выхода.
* **DLQ включена везде**, где output пишет в Elasticsearch; алерт по размеру каталога DLQ.
* **Детерминированный `document_id`** там, где возможны повторные доставки (Kafka, jdbc, P2P, http_poller, s3) — защита от дублей.
* **Мониторьте не только события, но и retry:** растущие счетчики ошибок output в `_node/stats` и постоянные `events.in > events.out` — ранний признак деградации целевой системы.
* **Persistent Queue для production** — `queue.type: persisted` + `queue.max_bytes` под диск; без PQ при рестарте теряются события в memory queue.
* **Sincedb на персистентном томе** — для `file` и `s3` входов выносите `sincedb_path` на volume, иначе при рестарте/редеплое позиция чтения потеряется.
* **Один `elasticsearch` output с динамическим `index`** — вместо нескольких статических выходов; меньше connection pools, выше throughput.
* **`acks => "all"` для Kafka output** — гарантия доставки; `acks => "0"` только для некритичных метрик.
* **Rate limiting на выходах** — `http` output: `pool_max`, `retry_options`; `kafka` output: не меняйте `retries` (бесконечные по умолчанию).
* **Health-check конвейера** — периодический `generator` input + `http` output к `/health` эндпоинту для проверки живости конвейера.
* Очистка стенда после экспериментов:

```bash
# Убрать тестовые конфиги входов/выходов
sudo rm /etc/logstash/conf.d/10-tcp-input.conf /etc/logstash/conf.d/90-kafka-output.conf

# Остановить сервис и проверить, что порты освобождены
sudo systemctl stop logstash
ss -tlnp | grep -E '5044|5514|8080|9600'
# → пустой вывод

# Состояние jdbc-импорта эксперимента (если создавалось)
sudo rm -f /var/lib/logstash/jdbc_last_run

# Sincedb file/s3 входов
sudo rm -f /var/lib/logstash/sincedb_*

# DLQ
sudo rm -rf /var/lib/logstash/dead_letter_queue/main/*

# Временные файлы s3 output
sudo rm -rf /tmp/logstash-s3/*
```

## Дополнительная информация

### См. также

* **[Logstash: Обзор](./logstash_overview.md)** — стадии обработки, Keystore, Persistent Queue, Monitoring API.
* **[Logstash: Конвейеры, фильтры и производительность](./logstash_pipelines.md)** — архитектура конвейеров, порядок фильтров, тюнинг, DLQ.
* **[Logstash: Условные операторы и sprintf](./logstash-conditionals.md)** — синтаксис `if`/`else`, семантика веток, field references и sprintf-подстановки.
* **[Logstash: Backpressure, batching](./logstash_backpressure_batching.md)** — поведение входов при backpressure, настройка батчей.
* **[Сетевые требования Elasticsearch](../elasticsearch_network_requirements.md)** — TLS-конфигурации `beats` и `tcp` входов Logstash, порты, требования к латентности.
* **[Grok и Dissect Patterns](../grok_dissect_patterns.md)** — паттерны парсинга и troubleshooting многострочных записей.
* **[Filebeat: Обзор](../filebeat_overview.md)** — многострочность и парсеры на стороне агента (альтернатива multiline-кодеку).
* **[Elasticsearch: Ingest Pipelines](../Elasticsearch/elasticsearch_ingest_pipelines.md)** — обработка на стороне кластера как альтернатива фильтрам Logstash.
* **[Логи: временные метки и запоздавшие события](../log-timestamps-and-late-events.md)** — работа с `@timestamp`, `_dateparsefailure`, late-arriving events.
* **[Семантика доставки и дедупликация](../log-delivery-and-deduplication.md)** — `fingerprint`, `document_id`, at-least-once vs exactly-once.
* **[Logstash: Фильтры](./logstash-filter-plugins.md)** — фильтры `date`, `translate`, `split`, `clone`, `throttle`, `fingerprint` у входов/выходов.
* **[Plugins: Inputs (Официально)](https://www.elastic.co/docs/reference/logstash/plugins/plugins-inputs-tcp)** — справочник всех входных плагинов (beats, file, http, http_poller, kafka, jdbc, s3, tcp, udp, syslog, generator, dead_letter_queue, stdin).
* **[Plugins: Outputs (Официально)](https://www.elastic.co/docs/reference/logstash/plugins/plugins-outputs-elasticsearch)** — справочник выходных плагинов (elasticsearch, kafka, http, file, s3, stdout, stderr, pagerduty, email, slack).
