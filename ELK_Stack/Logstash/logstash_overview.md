# Logstash: Обзор

**Актуально для:** Logstash 8.19 (LTS) / 9.5.x

> Эта заметка является частью обзора [ELK стека](../elk_stack_overview.md) и служит основной точкой входа для изучения Logstash.
>
> **Детальное описание архитектуры конвейеров, фильтров и оптимизации** — в заметке **[Logstash: Конвейеры, фильтры и производительность](./logstash_pipelines.md)**.

## Определения

* **Logstash** — серверный конвейер обработки данных (Dataflow Engine) с открытым исходным кодом. Позволяет принимать данные из множества источников одновременно, преобразовывать их и отправлять в различные хранилища.
* **Pipeline (Конвейер)** — логическая единица обработки данных, состоящая из стадий ввода (input), фильтрации (filter) и вывода (output).
* **Event (Событие)** — базовая единица данных, представляющая собой JSON-подобную структуру, проходящую через конвейер.
* **Codec (Кодек)** — плагин сериализации/десериализации, работающий на границах конвейера: превращает входной поток байтов в события (например, `json`, `multiline`) и события обратно в поток при выводе (`json_lines`, `rubydebug`).
* **Worker** — поток обработки внутри одного конвейера. Каждый воркер получает батч событий из очереди и прогоняет его через filter → output независимо от других воркеров.
* **Batch** — порция событий, выдаваемая воркеру за одну итерацию (размер задается `pipeline.batch.size`, по умолчанию 125; максимальное время добора событий — `pipeline.batch.delay`, 50 мс).
* **ECS (Elastic Common Schema)** — общий стандарт именования полей в Elastic Stack. Начиная с версии 8.x, Logstash по умолчанию работает в режиме совместимости с ECS (`v8`); отказаться можно на уровне плагина (`ecs_compatibility => disabled`), конвейера или всего процесса (`pipeline.ecs_compatibility: disabled` в `pipelines.yml`/`logstash.yml`).
* **Persistent Queue (PQ)** — механизм сохранения событий на диск для защиты от потери данных при сбое или перезагрузке узла.
* **Dead Letter Queue (DLQ)** — очередь событий, которые не удалось записать в целевую систему (например, из-за ошибок маппинга Elasticsearch). Позволяет исправить проблему и переработать события без потери. При переполнении (`dead_letter_queue.max_bytes`) политика `dead_letter_queue.storage_policy` определяет поведение: `drop_newer` (по умолчанию) отвергает новые события, `drop_older` вытесняет старейшие.
* **Keystore** — защищенное хранилище секретов Logstash (`logstash.keystore`), из которого значения подставляются в конфигурацию как `${ИМЯ_ПЕРЕМЕННОЙ}`, исключая пароли в открытом виде.

## Основные концепции

Logstash реализует модель потоковой обработки данных; перечисленные ниже механизмы применимы к конвейерам любой сложности.

### Ключевые характеристики (Версия 8.x+)

- **Модульность:** Весь функционал реализован через плагины (более 200 типов: inputs, filters, outputs, codecs).
- **Гарантии доставки:**
    - **Memory Queue:** Высокая скорость, но данные теряются при сбое процесса.
    - **Persistent Queues (PQ):** Обеспечивают "at-least-once" доставку за счет записи событий на диск до подтверждения их получения выходом (output).
    - **Dead Letter Queues (DLQ):** Сбор событий, которые не удалось записать в Elasticsearch (например, ошибки маппинга).
- **Безопасность (Security by Default):**
    - **SSL/TLS:** В версии 8.x защищенные соединения с Elasticsearch включены по умолчанию.
    - **Logstash Keystore:** Инструмент для безопасного хранения секретов (пароли, API-ключи), исключающий их использование в открытом виде в `.conf` файлах.
    - **Запуск от непривилегированного пользователя:** с 9.0 Logstash отказывается стартовать от суперпользователя (`allow_superuser: false` по умолчанию) — сервис работает от пользователя `logstash`.
- **Централизованное управление:** Centralized Pipeline Management — создание и управление конвейерами из Kibana (subscription-фича; требует настройки `xpack.management.pipeline.id` и роли `logstash_admin`; после включения локальные `pipelines.yml`, `path.config` и `config.string` становятся неактивны).
- **Горячая перезагрузка конфигурации:** изменения в `.conf` файлах конвейеров могут подхватываться без рестарта сервиса (опция `config.reload.automatic: true` или сигнал SIGHUP); настройки уровня `logstash.yml` требуют перезапуска.
- **Среда исполнения:** поставляется с собственным JDK (9.0–9.3 — OpenJDK 17; с 9.4 — OpenJDK 21 и JRuby 10.x), отдельная установка Java не требуется. Bundled JDK учитывает лимиты контейнеров (cgroup v1/v2, механизм JVM UseContainerSupport) — корректно определяет ограничения CPU/памяти в Docker и Kubernetes.
- **Современные интеграции:** плагины Elasticsearch input/filter поддерживают запросы ES|QL (техническое превью; фильтр — с версии плагина 8.17.4, требует Elasticsearch 8.11+); фильтр `elastic_integration` (GA, требует Logstash 8.7+) исполняет Ingest Pipelines кластера прямо внутри Logstash — при подключении к Elasticsearch 9.2+ нужна версия плагина не ниже 9.2.

### Стадии обработки данных

Logstash работает по модели **Input → Filter → Output**:

1. **Input (Ввод):** Сбор данных. Примеры конфигураций входных плагинов (beats, syslog, tcp/udp, http, kafka, jdbc) и их опций — в заметке **[Входы, выходы и маршрутизация](./logstash_inputs_outputs.md)**.
    - `beats`: Прием данных от Filebeat/Metricbeat.
    - `kafka`: Чтение из очередей сообщений.
    - `http`: Прием данных через HTTP POST.
    - `jdbc`: Выполнение SQL-запросов для импорта данных из БД.
2. **Filter (Фильтрация):** Парсинг, нормализация и обогащение.
    - `grok` / `dissect`: Разбор неструктурированных строк.
    - `mutate`: Переименование, удаление и изменение типов полей.
    - `geoip`: Определение географии по IP-адресу.
    - `elasticsearch`: Поиск данных в Elastic для обогащения текущего события.
3. **Output (Вывод):** Отправка данных. Маршрутизация по условиям `if`/`else`, retry-семантика и надежность bulk-запросов — в заметке **[Входы, выходы и маршрутизация](./logstash_inputs_outputs.md)**.
    - `elasticsearch`: Основной выход с поддержкой Data Streams.
    - `kafka` / `s3` / `http`: Отправка в сторонние системы.

На каждой стадии подключаются **codecs**: например, вход `beats` уже принимает декодированные события от агента, а вход `tcp` нуждается в кодеке (`line`, `json`, `multiline`) для превращения потока байтов в события. Модель исполнения: каждый воркер берет батч из очереди, последовательно применяет все фильтры ко всем событиям батча, затем передает результат в output; подтверждение (ACK) события возвращается в очередь только после успешной записи выходным плагином — так реализуется at-least-once семантика с включенной PQ.

### Наблюдаемость и мониторинг

- **Monitoring API:** HTTP-эндпоинт (порт 9600; по умолчанию первый свободный из диапазона 9600–9700) для получения метрик (throughput, latency, heap usage).
- **Elastic Agent Integration:** Рекомендуемый способ мониторинга здоровья Logstash в современных инсталляциях; метрики также можно экспортировать через OpenTelemetry в любой OTLP-совместимый бэкенд.
- **Slow Log:** Логирование событий, обработка которых занимает слишком много времени. Настраивается в `logstash.yml` порогами `slowlog.threshold.warn/info/debug/trace` (по умолчанию `-1` — отключено; единицы: `nanos`/`micros`/`ms`/`s`/`m`/`h`/`d`); в записи — полное событие и конфигурация фильтров, ответственных за замедление.
- **Node Stats, Hot Threads и Health Report:** эндпоинты `_node/stats` (метрики плагинов, очередей, JVM), `_node/hot_threads` (разбор самых нагруженных Java-потоков; `?human=true` — текстовый вид) и `_health_report` (сводный статус `green`/`unknown`/`yellow`/`red` с объяснением проблем через indicators: symptom, details, impacts, diagnosis) — основа для алертинга без внешних систем.
- Для использования устаревшего внутреннего сбора метрик (legacy collection) в 9.0+ требуется явно разрешить его настройкой `xpack.monitoring.allow_legacy_collection: true`.
- Метрики производительности и методика анализа backpressure разобраны в разделе «Мониторинг производительности» заметки [о конвейерах](./logstash_pipelines.md#мониторинг-производительности).

## Практические сценарии

Сценарии упорядочены от подготовки стенда к production-эксплуатации: требования, секреты, приём данных, надёжность и мониторинг.

### Предварительные требования

Для воспроизведения сценариев необходимы:

1. Logstash 8.19 (LTS) или 9.x. Если развертывание еще не создано — базовый стек поднимается по руководству [Развертывание ELK стека в Docker Compose](../Tutorials/practical_setup_with_docker.md); официальный образ — `docker.elastic.co/logstash/logstash:9.x.y` (с 9.0 базовый образ — UBI9, в производных образах пакетный менеджер `microdnf` вместо `apt`).
2. Доступный кластер Elasticsearch 8.x/9.x с HTTPS и учетными данными (API key или пользователь с ролью на запись индексов).
3. Свободные порты: **5044** (прием от Beats), **9600** (Monitoring API).
4. Ресурсы: минимум 2 ГБ ОЗУ для теста; production-узел — 8–16 ГБ ОЗУ и SSD под Persistent Queue.
5. Проверка готовности:

```bash
# Статус процесса и версия
bin/logstash --version
# → logstash 9.5.5

# Monitoring API отвечает
curl -s localhost:9600/?pretty
# → {"host":"...","version":"9.5.5","http_address":"127.0.0.1:9600"}
```

### Файлы конфигурации

- **`logstash.yml`**: Глобальные параметры (пути, настройки очередей, API). Поддерживает интерполяцию переменных окружения и секретов Keystore в стиле bash: `${VAR}` и `${VAR:default}` (значение по умолчанию).
- **`pipelines.yml`**: Определение нескольких независимых конвейеров.
- **`jvm.options`**: Настройка Heap Memory (рекомендуется 50-75% от ОЗУ системы, но не более 31 ГБ; на практике для типовых нагрузок достаточно 4–8 ГБ — см. тюнинг в заметке о [конвейерах](./logstash_pipelines.md#оптимизация-и-тюнинг-logstash-9x)).
- **`log4j2.properties`**: Конфигурация логирования самого Logstash (уровни, ротация, формат вывода).

Расположение файлов: пакетная установка — `/etc/logstash/` (настройки), `/usr/share/logstash/bin/` (утилиты), `/var/lib/logstash/` (данные PQ/DLQ), `/var/log/logstash/` (логи). В Docker — всё в `/usr/share/logstash/config/`.

Минимальный рабочий `logstash.yml` для тестового стенда:

```yaml
node.name: ls-node-01
path.data: /var/lib/logstash
pipeline.workers: 2          # число воркеров (по умолчанию = числу CPU)
pipeline.batch.size: 125     # событий на итерацию воркера
api.enabled: true            # Monitoring API (включен по умолчанию)
api.http.host: 127.0.0.1     # по умолчанию — только loopback
api.http.port: 9600          # по умолчанию первый свободный из диапазона 9600-9700
queue.type: memory           # memory | persisted
```

### Настройка секретов через Keystore

Пароли и API-ключи не должны попадать в `.conf` файлы и Git. Решение — Keystore.

**Шаг 1. Создайте хранилище** (переменная `LOGSTASH_KEYSTORE_PASS` защищает сам keystore; флаг `-E` сохраняет переменную при sudo):

```bash
set +o history
export LOGSTASH_KEYSTORE_PASS='Str0ngP@ss'
set -o history
sudo -E /usr/share/logstash/bin/logstash-keystore --path.settings /etc/logstash create
# → Created Logstash keystore at /etc/logstash/logstash.keystore
```

**Шаг 2. Добавьте секреты** (значение вводится интерактивно, не попадает в history шелла):

```bash
sudo -E /usr/share/logstash/bin/logstash-keystore --path.settings /etc/logstash add ES_API_KEY
# → Successfully added Logstash keystore entry 'ES_API_KEY'

sudo -E /usr/share/logstash/bin/logstash-keystore --path.settings /etc/logstash list
# → ES_API_KEY
```

**Шаг 3. Используйте в конфигурации** как обычную переменную окружения: `api_key => "${ES_API_KEY}"`.

Нюансы: пароль защищает сам keystore и должен быть доступен процессу Logstash через переменную `LOGSTASH_KEYSTORE_PASS` (например, через `/etc/sysconfig/logstash` или окружение systemd-юнита) — без неё запущенный экземпляр не прочитает keystore; имена ключей (с 9.0.1) ограничены буквами, цифрами, `_` и `.` и не могут начинаться с цифры; файл `logstash.keystore` должен быть доступен пользователю `logstash` (например, `chown logstash:logstash`); альтернатива для контейнеров — передача секретов через переменные окружения `${VAR}` из secrets-менеджера.

### Пример конфигурации: прием данных (стандарт ECS)

Пример конвейера, использующего лучшие практики 8.x: переменные окружения, секреты и поддержку Data Streams.

```conf
input {
  # Прием данных от агентов Filebeat
  beats {
    port => 5044
  }
}

filter {
  # Использование ECS полей (host.ip вместо host_ip)
  if [message] =~ /^\{.*/ {
    json {
      source => "message"
      target => "json_payload"
    }
  }

  # Обогащение данных через GeoIP
  if [source][ip] {
    geoip {
      source => "[source][ip]"
      target => "[source][geo]"
    }
  }
}

output {
  elasticsearch {
    hosts => ["${ES_URL}"]
    # Использование API Key из Keystore
    api_key => "${ES_API_KEY}"
    # Поддержка Data Streams (рекомендуется для логов)
    action => "create"
    index => "logs-generic-default"
    ssl_certificate_authorities => ["/etc/logstash/certs/ca.crt"]
  }
}
```

Объяснение ключевых параметров:

| Параметр | Назначение |
| :--- | :--- |
| `beats { port => 5044 }` | Открывает порт приема протокола Beats/Elastic Agent; агент настраивается на вывод в `host:5044` |
| `if [message] =~ /^\{.*/` | Условие: обрабатывать только сообщения, начинающиеся с `{` (защита от JSON-парсинга обычного текста) |
| `json { source/target }` | Разбор JSON из поля `message` во вложенный объект `json_payload`; без `target` поля влились бы в корень события |
| `geoip { source, target }` | Обогащение по IP из ECS-поля `[source][ip]`; результат кладется в `[source][geo]` (city, country_name, location) |
| `api_key` | Аутентификация вместо user/password; значение формата `id:api_key` из Keystore |
| `action => "create"` + `index => logs-generic-default` | Режим Data Streams: каждое событие создает новый документ (только append); имя должно соответствовать шаблону `<type>-<dataset>-<namespace>` и совпадать со значениями полей `data_stream.*` в событиях |
| `ssl_certificate_authorities` | CA-сертификат для проверки TLS-соединения с кластером |

**Валидация:** запустите конвейер, отправьте тестовое событие от Filebeat (или `nc localhost 5044` не даст результата — протокол бинарный, используйте агента), затем проверьте прием:

```bash
# В Kibana Dev Tools
GET logs-generic-default/_search
# → hits.total.value >= 1, в документе есть json_payload и/или source.geo.country_name
```

### Проверка конфигурации и запуск

Перед каждым изменением проверяйте синтаксис — это предотвращает простой продакшн-конвейера:

```bash
# Тест всех конфигураций без запуска (-t = --config.test_and_exit)
sudo /usr/share/logstash/bin/logstash --path.settings /etc/logstash -t
# → [INFO ][logstash.runner ] Using config.test_and_exit mode...
# → Configuration OK

# Быстрый эксперимент без файлов: stdin -> разбор -> вывод на экран
bin/logstash -e 'input { stdin{} } filter { mutate { add_field => {"env" => "test"} } } output { stdout { codec => rubydebug } }'
# после ввода текста печатает полное событие и завершается
```

Запуск как сервиса:

```bash
sudo systemctl enable --now logstash
systemctl status logstash
# → Active: active (running)

sudo journalctl -u logstash -f
# следите за строкой "Pipelines running" и отсутствием [ERROR]
```

Горячая перезагрузка конфигурации конвейеров (без рестарта):

```yaml
# logstash.yml
config.reload.automatic: true   # проверять изменения (интервал — config.reload.interval, по умолчанию 3s; единица обязательна)
config.support_escapes: true
ssl.reload.automatic: true      # GA с 9.5: автоматическая перезагрузка TLS-файлов; требует config.reload.automatic
```

После правки `.conf` дождитесь в логе строки `Reloaded config` либо отправьте процессу `SIGHUP`: `sudo kill -HUP $(pgrep -f logstash)`. Помните: reload применяется только к конфигурациям конвейеров; изменения `logstash.yml`, `pipelines.yml` и `jvm.options` требуют рестарта.

### Настройка Persistent Queue для защиты от потери данных

Memory queue теряет события при падении процесса. Для production включите дисковую очередь в `logstash.yml`:

```yaml
queue.type: persisted              # включить PQ
queue.max_bytes: 4gb               # размер КАЖДОЙ очереди конвейера (по умолчанию 1024mb)
queue.checkpoint.writes: 1024      # принудительный чекпоинт каждые N записей (максимум надежности: 1, ценой IOPS)
queue.checkpoint.acks: 1024        # то же для подтверждений (0 = без ограничений)
```

Как это работает: очередь хранится набором страниц-файлов (`queue.page_capacity`, по умолчанию 64mb); при чекпоинте Logstash делает `fsync` head-страницы и атомарно обновляет файл состояния. События, не попавшие в чекпоинт, теряются при аварийном завершении — поэтому параметр `queue.checkpoint.writes` это прямой trade-off «надежность против производительности». Дополнительный лимит `queue.max_events` (по умолчанию 0 — без ограничений) при одновременном задании с `max_bytes` срабатывает по тому критерию, что достигнут раньше. Когда очередь заполняется, Logstash включает **backpressure**: input-плагины приостанавливают прием (beats перестает принимать новые соединения), пока output не подтвердит часть событий. Опционально `queue.drain: true` заставит процесс вычитывать очередь до конца при контролируемой остановке; `pipeline.unsafe_shutdown: true` (по умолчанию `false`) разрешает завершение с потерей inflight-событий — только для аварийных случаев.

Ориентир размера: `поток_байт/сек * часы_допустимого_простоя_хранилища * 3600 * 1.10` (10% запас на метаданные). Пример: 3.6 МБ/с и запас на 12 часов простоя ES → ~50 ГБ.

Свежее в ветке 9.x: настройка `queue.compression` (общедоступна с 9.2) сжимает события на диске алгоритмом ZSTD (`speed`/`balanced`/`size`, по умолчанию `none`); периодические чекпоинты `queue.checkpoint.interval` объявлены устаревшими с 9.1 (не оказывают эффекта и будут удалены). Важно: очередь со сжатыми событиями не читается более старыми версиями Logstash — включайте сжатие только после валидации конвейеров на 9.2+ (rollback-barrier); в 9.2.0 известная проблема при `queue.max_bytes` больше 2 ГиБ.

**Валидация:** утилиты `pqcheck` (состояние страниц очереди) и `pqrepair` (восстановление поврежденной очереди):

```bash
/usr/share/logstash/bin/pqcheck /var/lib/logstash/queue/main/
# → checkpoint.head, fully-acked: NO, page.N size: ...
#   pageNum=..., elementCount=..., isFullyAcked=no
```

Если `elementCount` растет и не снижается — output не успевает (см. troubleshooting).

### Мониторинг через Node Stats и Monitoring API

Быстрая диагностика узла без внешних инструментов:

```bash
# Общие метрики узла: память JVM, события, очереди
curl -s 'localhost:9600/_node/stats?pretty' | grep -A5 '"events"'
# → "in": 123456, "filtered": ..., "out": 123456

# Метрики конкретных конвейеров
curl -s 'localhost:9600/_node/stats/pipelines?pretty'
# → {"pipelines":{"main":{"events":{"in":...,"out":...},"queue":{...}}}}

# Сводное здоровье узла: статус и причины деградации (indicators с symptom/diagnosis)
curl -s 'localhost:9600/_health_report?pretty'
# → {"status":"green","indicators":{...}}

# Самые нагруженные потоки JVM (диагностика высокой загрузки CPU)
curl -s 'localhost:9600/_node/hot_threads?human=true'
# → текстовый разбор: "% of cpu usage by <state> thread named '<имя>'"
```

Интерпретация: `events.in == events.out && queue.size стабилен` — узел справляется; рост `queue.size` при высоком `worker_utilization` — узкое место в фильтрах (масштабируйте воркеров или оптимизируйте пайплайн, детали в [заметке о конвейерах](./logstash_pipelines.md)). Для постоянного мониторинга направляйте метрики в кластер через Elastic Agent (integration Logstash) и смотрите готовые дашборды в Kibana.

### Управление плагинами

```bash
# Список установленных
bin/logstash-plugin list
# → logstash-input-beats, logstash-filter-geoip, ...

# Поиск по имени
bin/logstash-plugin list --verbose | grep geoip

# Установка из публичного репозитория RubyGems
sudo bin/logstash-plugin install logstash-output-influxdb
# → Installation successful

# Установка в изолированной сети (air-gapped): скачать gem, затем
sudo bin/logstash-plugin install /tmp/logstash-output-influxdb-*.gem

# Обновление и удаление
sudo bin/logstash-plugin update logstash-input-beats
sudo bin/logstash-plugin remove logstash-output-influxdb
```

После установки/удаления плагина перезапустите сервис — плагины загружаются при старте конвейера.

## Дополнительная информация

Сравнения с альтернативами, совместимость версий и типовые отказы.

### Logstash vs. Elastic Agent

В современном Elastic Stack выбор между агентом и Logstash зависит от сложности обработки.

| Характеристика | Elastic Agent | Logstash |
| :--- | :--- | :--- |
| **Управление** | Fleet (Централизованно из Kibana) | Файлы конфигурации / IaC |
| **Сложность обработки** | Ingest Pipelines (на узлах ES) | Богатые фильтры (на узлах Logstash) |
| **Ресурсы** | Легковесный (C/Go) | Тяжелый (Java/JVM) |
| **Обогащение** | Ограничено данными в ES | JDBC, HTTP, внешние словари |
| **Сценарий** | Стандартный сбор логов и метрик | Сложный ETL, агрегация, буферизация |

### Logstash vs. Vector

| Характеристика | Logstash | Vector |
| :--- | :--- | :--- |
| **Язык** | Java / JRuby | Rust |
| **Производительность** | Средняя (JVM overhead) | Экстремально высокая |
| **Экосистема** | Максимальная зрелость | Активно развивается |
| **Конфигурация** | Кастомный DSL | TOML / YAML / JSON |

**Рекомендация:** Используйте Logstash как центральное звено ("Heavy Lifter") для сложного обогащения данных из внешних систем или когда требуется глубокая интеграция с наследием Elastic Stack. Для пограничного сбора и передачи данных ("Edge collection") отдавайте предпочтение Elastic Agent или Vector.

### Совместимость версий с Elastic Stack

* Общее правило обновления стека: сначала Elasticsearch, затем Logstash, затем Kibana.
* **Исключение с `elastic_integration`:** этот фильтр встраивает компоненты Ingest Node определенной версии Elasticsearch, поэтому версия Logstash должна быть **не ниже** версии кластера. При переходе стека на новую мажорную версию обновляйте Logstash **до** обновления Kibana; комбинация Logstash 8.19 + Elasticsearch/Kibana 9.x с этим фильтром не поддерживается.
* Плагины `elasticsearch` output/filter принимают API-ключи в форматах `id:api_key`, base64-кодированном виде и облачных ключах `essu_`; неподдерживаемый формат отклоняется на старте.
* **Breaking changes 9.0:** удалены модули (netflow, azure, ArcSight и сам фреймворк модулей), ingest-converter (аналог — фильтр `elastic_integration`), integration-плагин Enterprise Search; устаревшие SSL-настройки плагинов и параметры `http.*` (заменены на `api.*`) удалены; минимум Java 11; базовый Docker-образ — UBI9; незаконные значения тегов теперь порождают тег `_tagsparsefailure` и записываются в поле `_tags`.
* **Breaking changes 9.4:** минимальная версия JDK — 21 (JRuby обновлён до 10.x).
* **Breaking changes 9.5:** bundled Kafka-integration обновлён с 11.x до 12.x (Kafka client 4.x) — конфигурации с `partitioner => "default"`/`"uniform_sticky"` не стартуют; удалён устаревший режим `concurrency => "legacy"` у output-плагинов; плагин `logstash-output-pipe` исключён из дефолтного набора (установите вручную до обновления).

### Типичные проблемы и их решение (Troubleshooting)

1. **Тег `_grokparsefailure` у части событий.**
   Причина: сообщение не соответствует шаблону `%{...}`.
   Диагностика: вставьте образец сообщения в Grok Debugger (Kibana Dev Tools) и итеративно правьте паттерн.
   Решение: комбинируйте `dissect` для стабильной части строки и `grok` только для остатка; добавьте `tag_on_failure => ["parse_failed"]` и маршрут неудачных событий в DLQ/отдельный индекс для разбора.
2. **Beats/Agent не может подключиться: connection refused на 5044.**
   Причины: конвейер упал при старте (смотрите `journalctl -u logstash`), порт занят другим процессом, firewall.
   Диагностика: `ss -tlnp | grep 5044`; поиск `[ERROR]` в логе старта; `bin/logstash -t` для проверки конфига.
3. **`OutOfMemoryError` или долгие GC-паузы.**
   Причины: маленький heap, гигантские события, слишком много воркеров на один heap.
   Решение: выставите равные `-Xms`/`-Xmx` в `jvm.options` (или `LS_JAVA_OPTS` в Docker); ограничьте размер событий; снизьте `pipeline.batch.size`.
4. **Диск заполняется файлами `page.N` в `/var/lib/logstash/queue`.**
   Причина: суммарный `queue.max_bytes` всех конвейеров превышает объем диска, либо output недоступен и backpressure копит данные.
   Решение: пересчитайте размер по формуле выше; проверьте доступность Elasticsearch; убедитесь, что страницы подтверждаются (`elementCount` в `pqcheck` снижается).
5. **Изменения в `.conf` не применяются.**
   Причина: авто-reload выключен, либо правился `logstash.yml`/`pipelines.yml` (они не релоадятся).
   Решение: включите `config.reload.automatic: true`, отправьте SIGHUP или перезапустите сервис.
6. **Ошибки маппинга (HTTP 400, `document_parsing_exception`).**
   Поведение: события автоматически попадают в DLQ (если `dead_letter_queue.enable: true`), конвейер продолжает работу.
   Решение: исправьте маппинг/шаблон индекса, затем перечитайте события input-плагином `dead_letter_queue` (пример в [заметке о конвейерах](./logstash_pipelines.md)).
7. **Конвейер медленный, события задерживаются.**
   Диагностика: `_node/stats/pipelines` — сравните `events.in/out` в секунду, посмотрите `worker_utilization` и время жизни в очереди.
   Решение: увеличьте `pipeline.workers` до числа ядер, оптимизируйте порядок фильтров («Dissect first, Grok last»), вынесите тяжелые обогащения в `elastic_integration`/ingest-пайплайны кластера. Полная методика тюнинга — в [заметке о конвейерах](./logstash_pipelines.md#оптимизация-и-тюнинг-logstash-9x).
8. **После обновления стека падает фильтр `elastic_integration`.**
   Причина: рассинхронизация версий (см. раздел совместимости выше). Решение: обновите Logstash до версии, соответствующей Elasticsearch.
9. **Logstash не стартует: ошибка запуска от суперпользователя.**
   Причина: с 9.0 запуск от root запрещён по умолчанию (`allow_superuser: false`).
   Решение: запускайте сервис от пользователя `logstash` (как делает systemd-юнит по умолчанию); если запуск от root абсолютно необходим — `allow_superuser: true` в `logstash.yml` (не рекомендуется, ослабляет безопасность).

### Лучшие практики и очистка окружения

* **Секреты только через Keystore или variables окружения** — ни одного пароля в `.conf`, которые обычно коммитятся в Git вместе с инфраструктурой.
* **Сервис работает от пользователя `logstash`** — запуск от root запрещён с 9.0 (`allow_superuser: false`); исключение оформляется явно и документируется.
* **Всегда `-t` перед рестартом** после правки конфигурации; для критичных сред держите staging-узел с тем же конфигом.
* **PQ включена на каждом production-узле**, размер рассчитан под допустимый простой Elasticsearch; DLQ включена (`dead_letter_queue.enable: true`) и мониторится по объему.
* **Одна ответственность на конвейер:** разделяйте прием/обработку разных типов данных на разные pipeline в `pipelines.yml` (паттерн pipeline-to-pipeline описан в [заметке о конвейерах](./logstash_pipelines.md)).
* **Именование:** `NN-purpose.conf` внутри `conf.d` гарантирует предсказуемый порядок загрузки в одиночном конвейере.
* **Очистка тестового окружения** после экспериментов:

```bash
# Удалить тестовый конфиг и остановить сервис
sudo rm /etc/logstash/conf.d/test-pipeline.conf
sudo systemctl stop logstash

# Удалить накопившиеся данные очередей и DLQ (осторожно: невыгруженные события будут потеряны)
sudo rm -rf /var/lib/logstash/queue/* /var/lib/logstash/dead_letter_queue/*

# Удалить временные плагины
sudo bin/logstash-plugin remove <имя-плагина>

# Проверить, что порты освобождены
ss -tlnp | grep -E '5044|9600'
# → пустой вывод
```

### См. также

* **[Logstash: Конвейеры, фильтры и производительность](./logstash_pipelines.md)** — углубленная архитектура, агрегация, тюнинг.
* **[Logstash: Входы, выходы и маршрутизация](./logstash_inputs_outputs.md)** — конфигурации input/output-плагинов, условная маршрутизация, retry-семантика, multiline codec.
* **[Grok и Dissect Patterns](../grok_dissect_patterns.md)** — коллекция паттернов для парсинга логов.
* **[Ingest Pipelines](../Elasticsearch/elasticsearch_ingest_pipelines.md)** — альтернатива Logstash для простой обработки.
* **[Elastic Agent и Fleet](../Elasticsearch/elastic_agent_and_fleet.md)** — современная замена Logstash + Beats.
* **[ELK стек: Обзор](../elk_stack_overview.md)** — место Logstash в общей архитектуре стека.
* **[Logstash Reference (Официально)](https://www.elastic.co/guide/en/logstash/current/introduction.html)** — полный справочник настроек и плагинов.
* **[Logstash breaking changes (Официально)](https://www.elastic.co/docs/release-notes/logstash/breaking-changes)** — что ломается при переходе между мажорными версиями.
