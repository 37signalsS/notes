# Neo4j: Мониторинг и логи

**Актуально для:** Neo4j 2025.09.x / 5.26.x LTS

> **Редакции.** Эндпоинт метрик для Prometheus (`server.metrics.prometheus.enabled`), журнал
> `query.log` и `security.log` — возможности Enterprise Edition. В Community Edition доступны
> базовые метрики через JMX и CSV, а также `debug.log` и `neo4j.log`.
>
> **Статус:** Neo4j 5.26 LTS — текущая долгосрочная поддержка (до 2027-08). Neo4j 2025.09 — текущий ежеквартальный релиз. Проверяйте актуальность версий перед внедрением.

Логи и метрики — два разных сигнала от одного сервера. Логи отвечают на вопрос «что произошло»,
метрики — «как ведёт себя система во времени». Диагностика по одному только `query.log`
невозможна: он не показывает ни использование памяти, ни состояние чекпоинтов, ни задержки
пула соединений. Поэтому разделены на два файла: логи и метрики здесь, память, чекпоинты
и общая диагностика — в [обслуживании](./operations.md).

## Определения

| Термин | Значение |
| :--- | :--- |
| **DBMS** | Экземпляр Neo4j, управляющий одной или несколькими базами данных |
| **Page cache** | Кэш в RAM для store-файлов графа и индексов (не часть JVM heap) |
| **Checkpoint** | Момент в логе транзакций, начиная с которого возможно восстановление после сбоя |
| **Transaction log (WAL)** | Журнал упреждающей записи всех изменений; используется для crash recovery и PITR |
| **Bolt thread pool** | Пул потоков для обработки входящих Cypher-запросов через Bolt-протокол |
| **Query log** | Журнал выполненных запросов с деталями времени, планов и ресурсов (Enterprise) |
| **Security log** | Журнал событий аутентификации и авторизации (Enterprise) |

## Предварительные требования

Для настройки мониторинга Neo4j необходимы:

- **Neo4j:** Enterprise Edition для `query.log`, `security.log`, Prometheus endpoint, `CONTINUOUS`/`VOLUMETRIC` checkpoint; Community Edition — базовые метрики через JMX/CSV, `debug.log`, `neo4j.log`
- **Prometheus:** 2.45+ (поддержка `scrape_interval`, `for` в правилах, multi-window burn rate)
- **Grafana:** 10.0+ (переменные `$database`, provisioning dashboards)
- **Alertmanager:** 0.26+ (группировка, inhibition, silencing)
- **Доступ к серверу:** SSH/root для редактирования `neo4j.conf`, systemd unit, Log4j XML
- **Порты:** 7687 (Bolt), 7474 (HTTP), 2004 (Prometheus metrics) — последний **только localhost** без обратного прокси
- **Дисковое пространство:** минимум 2 ГБ под логи и CSV-метрики (ротация 7 файлов × 20 MB / 10 MiB)
- **ОС:** Linux с systemd (Ubuntu 22.04/24.04 LTS, RHEL/Rocky 9+)
- **Java:** OpenJDK 21 (включён в пакет Neo4j)

> **Версии Neo4j.** Community Edition не имеет `server.metrics.prometheus.enabled`, `query.log`, `security.log`, `CONTINUOUS`/`VOLUMETRIC` checkpoint. Эти возможности только в Enterprise.
>
> **Версии инструментов.** Prometheus 2.45+ необходим для `for` в alerting rules и `scrape_interval`. Grafana 10.0+ для dashboard provisioning и переменных `$database`.

## Валидация конфигурации перед запуском

Проверьте настройки без перезапуска сервера:

```bash
# 1. Эффективные значения конфигурации
cypher-shell -u neo4j -p <password> \
  "CALL dbms.listConfig() YIELD name, value WHERE name STARTS WITH 'server.metrics.' OR name STARTS WITH 'db.logs.query.' RETURN name, value ORDER BY name"

# 2. Проверка доступности порта метрик
ss -tlnp | grep 2004
# → LISTEN 0 128 127.0.0.1:2004 users:(("java",pid=1234,fd=45))

# 3. Проверка формата метрик
curl -s http://localhost:2004/metrics | head -30
# → должен содержать # HELP и # TYPE строки

# 4. Проверка прав на логи
ls -la /var/log/neo4j/
# → владелец neo4j:neo4j, права 640

# 5. Проверка systemd unit
systemctl cat neo4j | grep -E 'LimitNOFILE|LockMemory|ProtectSystem'
```

## Логи

### Файлы логов

| Файл | Содержимое | Параметр | По умолчанию |
| :--- | :--- | :--- | :--- |
| `neo4j.log` | Общая информация о работе сервера | — | `true` |
| `debug.log` | Данные для поддержки Neo4j | `server.logs.debug.enabled` | `true` |
| `query.log` | Выполненные запросы (Enterprise) | `db.logs.query.enabled` | `VERBOSE` |
| `security.log` | События безопасности (Enterprise) | `dbms.security.auth_enabled` | `true` |
| `http.log` | HTTP API | `dbms.logs.http.enabled` | `false` |
| `gc.log` | События сборки мусора JVM | `server.logs.gc.enabled` | `false` |

> Не путайте `neo4j.log` и `debug.log`. Первый — общий журнал сервера. Второй — технический
> журнал для диагностики вендором; начиная с 2025.01 он по умолчанию в формате JSON, и менять
> его формат не следует: это может лишить вас поддержки. Нужен другой формат — создайте
> дополнительный Appender, а не переделывайте существующий.

Для пакетов Debian/RPM журнал `neo4j.log` пишется в systemd, а не в файл:

```bash
journalctl --unit=neo4j -f
```

### Расположение файлов

Пути зависят от способа установки, и это частая причина «файла нет»:

| Дистрибутив | Конфигурация | Данные | Логи |
| :--- | :--- | :--- | :--- |
| tar.gz, Linux, Docker | `<NEO4J_HOME>/conf` | `<NEO4J_HOME>/data` | `<NEO4J_HOME>/logs` |
| Debian / RPM | `/etc/neo4j` | `/var/lib/neo4j/data` | `/var/log/neo4j` |

```bash
# Ask the server itself instead of guessing the layout
cypher-shell -u neo4j -p <password> \
  "CALL dbms.listConfig() YIELD name, value WHERE name IN ['server.directories.logs','server.directories.data'] RETURN name, value"
```

```bash
# Debian/RPM layout
tail -f /var/log/neo4j/debug.log
du -sh /var/lib/neo4j/data/databases/neo4j/
```

В Docker `neo4j.log` доступен через `docker logs <container>`.

### Конфигурация Log4j 2

Neo4j использует Log4j 2, и начиная с 2025.01 его конфигурация вынесена в XML-файлы в
`server.directories.configuration`:

| Файл | Обслуживает логи |
| :--- | :--- |
| `user-logs.xml` | `neo4j.log` |
| `server-logs.xml` | `debug.log`, `http.log`, `query.log`, `security.log` |

Пути к ним переопределяются параметрами `server.logs.user.config` и `server.logs.config`.
`gc.log` Log4j не обслуживает — он настраивается параметрами JVM, которые Neo4j выводит в
конфигурацию.

Ротация по умолчанию — при 20 MB, хранится 7 файлов:

```xml
<RollingRandomAccessFile name="Neo4jLog" fileName="${config:server.directories.logs}/neo4j.log"
                         filePattern="$${config:server.directories.logs}/neo4j.log.%02i">
    <PatternLayout pattern="%d{yyyy-MM-dd HH:mm:ss.SSSZ}{GMT+0} %-5p %m%n"/>
    <Policies>
        <SizeBasedTriggeringPolicy size="20 MB"/>
    </Policies>
    <DefaultRolloverStrategy fileIndex="min" max="7"/>
</RollingRandomAccessFile>
```

`fileIndex="min"` означает, что самая свежая ротация имеет наименьший номер. Сжатие
ротированных файлов включается суффиксом в `filePattern` — `.gz`, `.zip`, `.bz2`, `.deflate`,
`.pack200`.

> `<RollingRandomAccessFile>` пишет через буфер и очень быстр, но при падении сервера последние
> сообщения теряются. Если это неприемлемо для вас — используйте `<RollingFile>`.

Журнал GC:

```conf
server.logs.gc.enabled=true
server.logs.gc.rotation.keep_number=5
server.logs.gc.rotation.size=20MB
```

### `query.log`: разбор записи

`query.log` — основной источник данных о стоимости запросов, и его формат стоит знать, потому
что «медленный запрос» ищется именно по нему.

```conf
# Log only queries slower than 100ms
db.logs.query.enabled=INFO
db.logs.query.threshold=100ms
```

| Значение `db.logs.query.enabled` | Поведение |
| :--- | :--- |
| `OFF` | Полностью отключено |
| `INFO` | Логирует завершившиеся запросы дольше `db.logs.query.threshold` |
| `VERBOSE` | По умолчанию. Логирует старт и финиш всех запросов, порог игнорируется |

Дополнительные параметры: `db.logs.query.parameter_logging_enabled` (`true`),
`db.logs.query.max_parameter_length` (`2147483647`), `db.logs.query.transaction.enabled`
(`OFF`), `db.logs.query.transaction.threshold` (`0s`), `db.logs.query.plan_description_enabled`
(`false`), `db.logs.query.early_raw_logging_enabled` (`false`) — логирует текст запроса
и параметры до парсинга, **без обфускации паролей**, `db.logs.query.obfuscate_literals`
(`false`) — заменяет литераалы в тексте запроса на `_` при логировании, `db.logs.query.obfuscate_errors`
(`false`) — обфусцирует детали ошибок в логе.

Полезная находка для расследования инцидентов — логировать только медленные запросы вместо
всех: `VERBOSE` на нагруженной базе даёт огромный объём и сам становится нагрузкой.

Реальная запись (полный формат с учётом `dbms.logs.query.time_logging_enabled=true`):

```plain
2026-06-22 13:45:54.597+0000 INFO  id:34 - transaction id:6 - 195 ms: (planning: 185, cpu: 10, waiting: 0) - 328 B - 68 page hits, 0 page faults - bolt-session  bolt    neo4j-javascript/6.0.1      client/127.0.0.1:53864  server/127.0.0.1:7687>  neo4j - neo4j - MATCH (n:Person {name:'Tom Hanks'})-[:ACTED_IN]->(n1:Movie)<-[:DIRECTED]-(n2:Person {name:"Tom Hanks"}) RETURN n1.title - {} - runtime=pipelined - {app: 'query', container_app: 'workspace', type: 'user-direct', vendor: 'neo4j'}
```

| Фрагмент | Значение |
| :--- | :--- |
| `id:34` | Внутренний ID соединения; новый на каждое Bolt-соединение |
| `transaction id:6` | ID транзакции |
| `195 ms` | Полное wall-clock время = planning + cpu + waiting |
| `planning: 185` | Время построения плана. **Близко к общему времени — запрос компилируется заново** |
| `cpu: 10` | Время, проведённое процессором на выполнении запроса (суммируется при переключении потоков) |
| `waiting: 0` | Ожидание блокировок, удерживаемыми другими транзакциями |
| `328 B` | Всего байт heap, накопленных за время запроса |
| `68 page hits, 0 page faults` | Попадания и промахи page cache. **Ненулевой `page faults` — признак нехватки page cache** |
| `neo4j-javascript/6.0.1` | Драйвер и его версия |
| `client/...`, `server/...` | Адрес клиента и слушающий адрес сервера |
| `{}` | Параметры запроса |
| `{app: ..., type: ...}` | Метаданные транзакции |

**Как читать запись.** Доминирование `planning` означает проблему с кэшем запросов, а не с
данными: план строится заново, потому что запрос каждый раз приходит с другим текстом. Ненулевой
`waiting` — contention по блокировкам, проблема моделирования или размера батча. Большое
`page faults` — page cache меньше рабочего набора. Растущий `328 B` при большом числе
одновременных транзакций — повод поднять лимиты памяти транзакций. Ненулевой `cpu` при малом
`waiting` — запрос тратит время на вычисления, а не на ожидание; рост `cpu` без роста `planning`
указывает на неэффективный план (например, `NodeFullScan` вместо индекса).

> **Важно.** Поле `cpu` появляется только при включённом `dbms.logs.query.time_logging_enabled=true`
> (по умолчанию `false`). Без него запись имеет вид `195 ms: bolt-session ...` — без скобок
> и без разбивки на `planning`/`cpu`/`waiting`. Проверять наличие `dbms.logs.query.time_logging_enabled`
> стоит перед попытками парсинга по这三个 компонентам.

Включение плана в лог помогает при разборе конкретного инцидента, но постоянно использовать его
не стоит: подготовка и включение плана в лог дают ощутимую нагрузку.

```bash
# Slowest queries by wall time; VERBOSE format, duration is the 4th-from-last field
grep -oP 'INFO\s+id:\d+.*?' /var/log/neo4j/query.log | \
  awk '{for(i=1;i<=NF;i++) if($i ~ /^[0-9]+ ms:$/) print $(i-1), $0}' | sort -rn | head -20

# Count page faults — a rising total means page cache is undersized
grep -c 'page faults' /var/log/neo4j/query.log

# Requests that spent most time waiting on locks
grep 'waiting: [1-9]' /var/log/neo4j/query.log | head -20
```

### Динамические настройки логирования

Параметры `db.logs.query.*` меняются без перезапуска:

```cypher
-- Switch to threshold-based logging at runtime
CALL dbms.setConfigValue('db.logs.query.enabled', 'INFO')
CALL dbms.setConfigValue('db.logs.query.threshold', '100ms')

-- Reset to default
CALL dbms.setConfigValue('db.logs.query.enabled', '')
```

Ошибка видна сразу:

```cypher
CALL dbms.setConfigValue('db.logs.query.enabled', 'yes')
```

```plain
Failed to invoke procedure `dbms.setConfigValue`: Caused by: org.neo4j.graphdb.config.InvalidSettingException: Bad value 'yes' for setting 'db.logs.query.enabled': 'yes' not one of [OFF, INFO, VERBOSE]
```

## Метрики и мониторинг

### Эндпоинт Prometheus

Метрики публикуются на **отдельном порту 2004**, а не на HTTP-порту 7474:

```conf
# Enable the Prometheus endpoint. Default is false.
server.metrics.prometheus.enabled=true
# Default is localhost:2004
server.metrics.prometheus.endpoint=localhost:2004
```

```bash
curl -s http://localhost:2004/metrics | head -20
```

```plain
# HELP neo4j_dbms_page_cache_hit_ratio The ratio of hits to the total number of lookups in the page cache.
# TYPE neo4j_dbms_page_cache_hit_ratio gauge
neo4j_dbms_page_cache_hit_ratio 0.9971
```

> Эндпоинпт не имеет аутентификации и не шифрует трафик. Никогда не выставляйте
> `0.0.0.0:2004` наружу. Для удалённого сбора оставьте `localhost:2004` и закройте его
> firewall-правилом, либо поставьте на той же машине обратный прокси с TLS.

### Соглашение об именах метрик

Внутренние имена Neo4j используют точки, Prometheus их не поддерживает. При экспорте
происходит трансформация: точки заменяются на подчёркивания, префиксом добавляется `neo4j_`,
а к счётчикам добавляется суффикс `_total`. Исходное имя видно в строке `# HELP` вывода.

| Внутреннее имя | В Prometheus | Тип |
| :--- | :--- | :--- |
| `dbms.page_cache.hit_ratio` | `neo4j_dbms_page_cache_hit_ratio` | gauge |
| `dbms.page_cache.evictions` | `neo4j_dbms_page_cache_evictions_total` | counter |
| `dbms.page_cache.usage_ratio` | `neo4j_dbms_page_cache_usage_ratio` | gauge |
| `dbms.vm.heap.used` | `neo4j_dbms_vm_heap_used` | gauge |
| `dbms.vm.heap.max` | `neo4j_dbms_vm_heap_max` | gauge |
| `dbms.vm.gc.time_percent` | `neo4j_dbms_vm_gc_time_percent` | gauge |
| `dbms.bolt.connections_running` | `neo4j_dbms_bolt_connections_running` | gauge |
| `dbms.bolt.connections_idle` | `neo4j_dbms_bolt_connections_idle` | gauge |
| `dbms.bolt.connections_open` | `neo4j_dbms_bolt_connections_open` | gauge |
| `dbms.bolt.thread_pool_queue_size` | `neo4j_dbms_bolt_thread_pool_queue_size` | gauge |
| `database.<db>.check_point.duration` | `neo4j_database_<db>_check_point_duration` | gauge |
| `database.<db>.check_point.last_completed` | `neo4j_database_<db>_check_point_last_completed` | gauge |
| `database.<db>.transaction.last_committed_tx_id` | `neo4j_database_<db>_transaction_last_committed_tx_id` | gauge |
| `database.<db>.transaction.open_count` | `neo4j_database_<db>_transaction_open_count` | gauge |
| `database.<db>.db.query.execution_latency` | `neo4j_database_<db>_db_query_execution_latency_millis` | histogram |
| `database.<db>.count.node` | `neo4j_database_<db>_count_node` | gauge |
| `database.<db>.count.relationship` | `neo4j_database_<db>_count_relationship` | gauge |
| `database.<db>.count.property` | `neo4j_database_<db>_count_property` | gauge |
| `database.<db>.index.native.count` | `neo4j_database_<db>_index_native_count` | gauge |
| `database.<db>.index.fulltext.count` | `neo4j_database_<db>_index_fulltext_count` | gauge |

> Метрики с префиксом `neo4j_dbms_*` относятся ко всему DBMS, `neo4j_database_*` — к конкретной
> базе, в имени которой присутствует имя базы. Уровень `dbms` для диагностики одного сервера
> недостаточен: падение hit ratio на одной базе не видно за усреднённой метрикой.

### Ключевые метрики и пороги

| Метрика | Что показывает | Порог | Alert severity |
| :--- | :--- | :--- | :--- |
| `neo4j_dbms_page_cache_hit_ratio` | Доля попаданий в page cache | < 0.98 устойчиво 10m | warning |
| `neo4j_dbms_page_cache_usage_ratio` | Какая доля выделенного кэша занята | ≥ 1.0 устойчиво 5m | warning |
| `neo4j_dbms_vm_heap_used` | Использование кучи | > 90% max устойчиво | warning |
| `neo4j_dbms_vm_gc_time_percent` | Доля времени JVM в GC | > 25% устойчиво 15m | warning |
| `neo4j_database_<db>_check_point_duration` | Длительность checkpoint | > 80% интервала | warning |
| `neo4j_dbms_bolt_connections_running` | Соединения, исполняющие Cypher | > 80% thread_pool_max_size | warning |
| `neo4j_dbms_bolt_thread_pool_queue_size` | Очередь задач пула потоков | > 0 устойчиво | critical |
| `neo4j_database_<db>_transaction_open_count` | Открытые транзакции | Рост без спада | warning |
| `neo4j_database_<db>_db_query_execution_latency_millis` | Перцентили 95/99 задержек | p99 > 5s | warning |
| `neo4j_database_<db>_transaction_last_committed_tx_id` | Последний закоммиченный tx ID | Без роста 5m | critical |
| `neo4j_database_<db>_count_node` | Число узлов | Рост сверх плана capacity | info |
| `neo4j_dbms_page_cache_evictions_total` | Вытеснение страниц из кэша | Рост rate | warning |

**`usage_ratio` важнее, чем `hit_ratio`.** Низкий hit ratio означает «много промахов», но
`usage_ratio = 1.0` — это прямая рекомендация увеличить page cache, причём до того, как
производительность упадёт. Мониторить нужно обе метрики.

**`last_committed_tx_id` — метрика живости репликации.** Должна быть одной непрерывно растущей
линией. Если одна из линий вышла на плато или отстаёт, этот экземпляр перестал реплицировать
данные, и это надо исправлять немедленно, независимо от текущей нагрузки.

**`bolt_thread_pool_queue_size` — признак перегрузки.** Ненулевая очередь означает, что все
потоки пула заняты, и новые запросы ждут. Это прямой сигнал к увеличению `thread_pool_max_size`
или снижению нагрузки.

**Диагностика process-level.** CPU близко к 100% — нужны ядра; использование памяти
выше 95% — риск OOM; свободное место на диске нужно отслеживать на **всех** носителях, где
Neo4j пишет, включая журналы: исчерпание диска уводит базу в офлайн и создаёт риск повреждения
файлов.

### Конфигурация Prometheus

```yaml
scrape_configs:
  - job_name: neo4j
    scrape_interval: 15s
    static_configs:
      - targets: ['neo4j-01.internal:2004', 'neo4j-02.internal:2004']
        labels:
          environment: production
```

Для аутентифицированного сбора через обратный прокси добавьте `metrics_path` и `scheme` в
соответствии с его конфигурацией.

### Другие способы экспорта

| Способ | Параметры | По умолчанию |
| :--- | :--- | :--- |
| **JMX MBeans** | `server.metrics.jmx.enabled` | `true` |
| **CSV-файлы** | `server.metrics.csv.enabled` | `true` |
| **Graphite** | `server.metrics.graphite.enabled` | `false` |
| **Neo4j Ops Manager (NOM)** | Встроенный UI, включается при установке Enterprise | — |

JMX-эндпоинт по умолчанию слушается на порту **3637** (RMI-Registry) и, при включённом
`server.metrics.jmx`, является потенциальным вектором RCE: любая команда, которая может выполнить
JMX-операцию, может быть использована для загрузки и выполнения произвольного кода. Порт **должен
быть закрыт на сетевом уровне** или слушать только `localhost`. Подробно — в
[диагnostике JVM](./jvm_diagnostics.md#JMX-как-вектор-RCE).

CSV удобен для офлайн-разбора: файлы с интервалом в 30 секунд, 7 ротаций, 10 MiB на файл.

```conf
server.metrics.csv.enabled=true
server.directories.metrics=/var/lib/neo4j/metrics
server.metrics.csv.interval=30s
server.metrics.csv.rotation.keep_number=7
server.metrics.csv.rotation.size=10.00MiB
server.metrics.csv.rotation.compression=ZIP
```

CSV хорошо сжимается, поэтому `ZIP` почти всегда стоит включать.

### Практические примеры работы с CSV-метриками

```bash
# Просмотр доступных CSV файлов
ls -la /var/lib/neo4j/metrics/

# Разбор конкретной метрики (page cache hit ratio)
zcat /var/lib/neo4j/metrics/neo4j_dbms_page_cache_hit_ratio_*.csv.gz | tail -20

# Агрегация по часу для capacity planning
zcat /var/lib/neo4j/metrics/neo4j_database_neo4j_count_node_*.csv.gz | \
  awk -F, '{sum+=$2} END {print sum/NR}'

# Поиск пиков heap usage за сутки
zcat /var/lib/neo4j/metrics/neo4j_dbms_vm_heap_used_*.csv.gz | \
  awk -F, '$2 > max {max=$2} END {print "Max heap:", max}'
```

Graphite:

```conf
server.metrics.graphite.enabled=true
server.metrics.graphite.server=localhost:2003
server.metrics.graphite.interval=30s
server.metrics.prefix=neo4j
```

### Пул потоков Bolt

Каждая активная транзакция занимает поток из пула до своего закрытия, поэтому **максимум
одновременных транзакций определяет и размер пула**. Значения по умолчанию подходят большинству
нагрузок.

```conf
server.bolt.thread_pool_min_size=5
server.bolt.thread_pool_max_size=100
server.bolt.thread_pool_keep_alive=10m
```

`thread_pool_min_size` задаётся по средней нагрузке — лишние потоки без заданий только жгут
память. `thread_pool_max_size` — по пиковой, с учётом не только транзакций, но и подключений.
Слишком низкий максимум даёт ошибку об отсутствии свободных потоков, которая также попадает в
`neo4j.log`.


### Централизованная агрегация логов

По умолчанию `query.log`, `security.log` и `debug.log` пишутся локально в `server.directories.logs`.
На нескольких серверах это создаёт дисперсные источники, где «что произошло» приходится собирать
вручную. Архитектура агрегации — в общем [концептах агрегации логов](../../Concepts/Observability_and_Monitoring/log_aggregation.md);
здесь — специфика Neo4j.

| Подход | Как | Плюсы | Минусы |
| :--- | :--- | :--- | :--- |
| **Локальная ротация + `rsync`/`scp`** | Собирать `*.log` по расписанию | Просто, без доп. компонентов | Нет реалтайма, нет поиска |
| **Logstash / Filebeat** | Appender'ы или агент на хосте читают `*.log` и шлют в Elasticsearch/Loki | Реалтайм, централизованный поиск | Ещё одна система |
| **Log4j SocketAppender** | Прямая отправка логов на удалённый хост по TCP/UDP | Встроено в Log4j, без внешнего агента | Нет шифрования по умолчанию, нет буферизации при обрыве связи |
| **Neo4j Ops Manager (NOM)** | Встроенный Enterprise-инструмент: сбор логов и метрик с нескольких инстансов в один UI | Официальный, поддерживается вендором | Только Enterprise, только NOM |

Рекомендация: на production-инстансах включайте `server.logs.debug.enabled=true` — формат
`debug.log` (JSON с 2025.01) нужен вендору при расследовании инцидентов, и отключение не
экономит ни памяти, ни диска в измеряемом объёме.

### Практические примеры конфигурации Filebeat

```yaml
# filebeat.yml — отправка Neo4j логов в Elasticsearch/Loki
filebeat.inputs:
  - type: log
    enabled: true
    paths:
      - /var/log/neo4j/neo4j.log
      - /var/log/neo4j/debug.log
      - /var/log/neo4j/query.log*
      - /var/log/neo4j/security.log*
    fields:
      service: neo4j
      environment: production
    fields_under_root: true
    multiline.pattern: '^[0-9]{4}-[0-9]{2}-[0-9]{2}'
    multiline.negate: true
    multiline.match: after

  - type: log
    enabled: true
    paths:
      - /var/log/neo4j/gc.log*
    fields:
      service: neo4j
      type: gc
    fields_under_root: true

processors:
  - add_host_metadata: ~
  - add_docker_metadata: ~

output.elasticsearch:
  hosts: ["elasticsearch:9200"]
  index: "neo4j-logs-%{+yyyy.MM.dd}"

# Или для Loki:
# output.logstash:
#   hosts: ["logstash:5044"]
```

### Практические примеры Log4j SocketAppender

```xml
<!-- server-logs.xml — отправка логов на удалённый syslog/Logstash -->
<Socket name="RemoteLog" host="logstash.internal" port="5000" protocol="TCP">
  <PatternLayout pattern="%d{yyyy-MM-dd HH:mm:ss.SSSZ}{GMT+0} %-5p %m%n"/>
  <ReconnectionDelayMillis>5000</ReconnectionDelayMillis>
</Socket>

<Root level="INFO">
  <AppenderRef ref="RemoteLog"/>
  <AppenderRef ref="Neo4jLog"/>
</Root>
```

> **Важно:** SocketAppender не буферизует при обрыве связи — сообщения теряются. Для production используйте Filebeat с локальной буферизацией.

### Дашборды и алерты

Пороги из таблицы ключевых метрик становятся алертами, когда они оформлены как правила Prometheus
с временными окнами: мгновенное срабатывание на разовом скачке бесполезно, реагировать нужно на
устойчивое отклонение.

```yaml
# Правила для Neo4j (фрагмент)
groups:
  - name: neo4j
    rules:
      # Page cache не справляется: устойчиво ниже 98 % на протяжении 10 минут
      - alert: Neo4jPageCacheHitRatioLow
        expr: neo4j_dbms_page_cache_hit_ratio < 0.98
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "Page cache hit ratio {{ $value | humanizePercentage }} ниже 98 %"

      # Кэш переполнен: расширять page cache нужно до падения hit ratio
      - alert: Neo4jPageCacheExhausted
        expr: neo4j_dbms_page_cache_usage_ratio >= 1.0
        for: 5m
        labels:
          severity: warning

      # Сборщик мусора забирает время процессора
      - alert: Neo4jHighGcTime
        expr: neo4j_dbms_vm_gc_time_percent > 25
        for: 15m
        labels:
          severity: warning

      # Репликация встала: метрика перестала расти
      - alert: Neo4jReplicationStalled
        expr: changes(neo4j_database_<db>_transaction_last_committed_tx_id[5m]) == 0
        for: 5m
        labels:
          severity: critical

      # Две primaries: возможны расхождения из-за сетевых разрывов
      - alert: Neo4jMultiplePrimaries
        expr: sum(neo4j_database_<db>_cluster_raft_is_leader) > 1
        for: 1m
        labels:
          severity: warning
```

Два правила требуют пояснения, потому что их легко написать неправильно:

- **`last_committed_tx_id` проверяется через `changes()`**, а не сравнением с константой. Проверка «метрика не изменилась за 5 минут» ловит именно остановку репликации, в то время как сравнение абсолютных значений между серверами бессмысленно: значения у разных серверов различаются по определению.
- **`cluster.raft.is_leader` суммируется по базе.** Сумма должна быть равна 1. Значение больше 1 означает, что несколько членов считают себя лидером, — временные периоды так возможны, поэтому для этой метрии окно `for` короткое, а severity ниже, чем у остановки репликации.

Правила проверяйте до выката: синтаксис и корректность выражений проверяются `promtool`, общие
практики — в [Prometheus: rules](../../Prometheus/rules.md) и
[best practices](../../Prometheus/promtool_and_best_practices.md), доставка уведомлений — в
[Alertmanager](../../Prometheus/alertmanager.md).

### Расширенные правила алертинга (Multi-window Burn Rate)

Следующие правила используют подход multi-window burn rate для снижения alert fatigue.
См. [Monitoring Alerting Recommendations](../../Concepts/Observability_and_Monitoring/monitoring_alerting_recommendations.md).

```yaml
groups:
  - name: neo4j.burnrate
    interval: 30s
    rules:
      # Page cache hit ratio — burn rate подход
      - alert: Neo4jPageCacheHitRatioBurnRate
        expr: |
          (
            sum(rate(neo4j_dbms_page_cache_hit_ratio{job="neo4j"}[1m])) by (instance)
              /
            sum(rate(neo4j_dbms_page_cache_hit_ratio{job="neo4j"}[1h])) by (instance)
          ) > 14.4
            and
          sum(rate(neo4j_dbms_page_cache_hit_ratio{job="neo4j"}[1h])) by (instance) < 0.98
        for: 2m
        labels:
          severity: warning
        annotations:
          summary: "Page cache hit ratio burn rate высокий на {{ $labels.instance }}"
          runbook_url: "https://runbooks.example.com/neo4j-page-cache"

      # Heap usage — sustained high usage
      - alert: Neo4jHeapUsageHigh
        expr: |
          (
            neo4j_dbms_vm_heap_used / neo4j_dbms_vm_heap_max
          ) > 0.9
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "Heap usage > 90% на {{ $labels.instance }}"

      # GC time percent — multi-window
      - alert: Neo4jGcTimeBurnRate
        expr: |
          (
            sum(rate(neo4j_dbms_vm_gc_time_percent{job="neo4j"}[5m])) by (instance)
              /
            sum(rate(neo4j_dbms_vm_gc_time_percent{job="neo4j"}[1h])) by (instance)
          ) > 14.4
            and
          sum(rate(neo4j_dbms_vm_gc_time_percent{job="neo4j"}[1h])) by (instance) > 0.1
        for: 5m
        labels:
          severity: warning

      # Bolt thread pool queue — immediate alert
      - alert: Neo4jBoltThreadPoolQueueBacklog
        expr: neo4j_dbms_bolt_thread_pool_queue_size > 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "Bolt thread pool queue не пуст на {{ $labels.instance }}"

      # Checkpoint duration approaching interval
      - alert: Neo4jCheckpointDurationHigh
        expr: |
          neo4j_database_<db>_check_point_duration
            /
            (db.checkpoint.interval.time * 60 * 1000) > 0.8
        for: 5m
        labels:
          severity: warning

      # Transaction count growing without bound
      - alert: Neo4jTransactionCountGrowing
        expr: |
          rate(neo4j_database_<db>_transaction_open_count[15m]) > 0
        for: 10m
        labels:
          severity: warning

      # Replication lag — multi-window
      - alert: Neo4jReplicationLag
        expr: |
          (
            max(neo4j_database_<db>_transaction_last_committed_tx_id) by (instance)
              -
            min(neo4j_database_<db>_transaction_last_committed_tx_id) by (instance)
          ) > 10000
        for: 5m
        labels:
          severity: critical

      # Multiple primaries — split brain detection
      - alert: Neo4jMultiplePrimaries
        expr: sum(neo4j_database_<db>_cluster_raft_is_leader) by (database) > 1
        for: 1m
        labels:
          severity: critical

      # Disk space — filesystem level
      - alert: Neo4jDiskSpaceCritical
        expr: |
          (node_filesystem_avail_bytes{mountpoint="/var/lib/neo4j/data"} / node_filesystem_size_bytes{mountpoint="/var/lib/neo4j/data"}) < 0.1
        for: 5m
        labels:
          severity: critical
```

### Минимальный набор панелей Grafana для диагностики Neo4j

| Панель | Метрики | Зачем |
| :--- | :--- | :--- |
| Page cache | `neo4j_dbms_page_cache_hit_ratio`, `..._usage_ratio`, `..._evictions_total` | Главный индикатор достаточности памяти под кэш |
| Heap и GC | `neo4j_dbms_vm_heap_used`, `neo4j_dbms_vm_gc_time_percent` | Давление на JVM |
| Checkpoint | `neo4j_database_<db>_check_point_duration` | Успевает ли сброс страниц за интервал |
| Репликация | `neo4j_database_<db>_transaction_last_committed_tx_id` | Живость репликации по каждому серверу отдельно |
| Роли кластера | `neo4j_database_<db>_cluster_raft_is_leader` | Кто leader, не двоится ли leadership |
| Нагрузка | `neo4j_database_<db>_db_query_execution_latency_millis`, `neo4j_dbms_bolt_connections_running` | Перцентили задержек и загрузка пула |
| Рост данных | `neo4j_database_<db>_count_node`, `..._count_relationship` | Планирование ёмкости |

Общие правила построения панелей, шаблонизации с переменными `$database` и provision — в
[Grafana: provisioning](../../Grafana/grafana_provisioning.md),
[Grafana: templating](../../Grafana/grafana_templating.md) и
[Grafana: alerting](../../Grafana/alerting/concepts.md).

Официальный набор essential-метрик с описанными порогами — в документации; он совпадает с
таблицей ключевых метрик выше и служит основанием для алертов.

## Устранение неполадок

| Проблема | Симптом | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **Метрики не собираются** | Prometheus показывает `no data` для `neo4j_*` | `curl localhost:2004/metrics` — пустой ответ или 404 | Проверить `server.metrics.prometheus.enabled=true`, порт 2004 слушается, firewall не блокирует |
| **Метрики с неверными именами** | `dbms.page_cache.hit_ratio` вместо `neo4j_dbms_page_cache_hit_ratio` | `curl localhost:2004/metrics \| grep HELP` | Это ожидаемое поведение: Neo4j экспортирует с префиксом `neo4j_` и подчёркиваниями |
| **Page cache hit ratio низкий** | `< 0.98` устойчиво | `neo4j_dbms_page_cache_usage_ratio` ≈ 1.0 | Увеличить `server.memory.pagecache.size` по формуле `1.2 × (данные + нативные индексы)` |
| **Heap растёт до OOM** | `neo4j_dbms_vm_heap_used` → max | `jcmd <PID> GC.heap_info`, `SHOW TRANSACTIONS` по `currentQueryAllocatedBytes` | Найти длинные транзакции, увеличить heap, задать `initial_size = max_size` |
| **GC time percent высокий** | `neo4j_dbms_vm_gc_time_percent` > 25% | GC логи (`server.jvm.additional=-Xlog:gc*`), NMT | Увеличить heap, найти premature promotion, проверить `thread_pool_max_size` |
| **Bolt thread pool exhausted** | `neo4j_dbms_bolt_thread_pool_queue_size` > 0 | `neo4j_dbms_bolt_connections_running` ≈ `thread_pool_max_size` | Увеличить `server.bolt.thread_pool_max_size`, оптимизировать долгие запросы |
| **Checkpoint не успевает** | `neo4j_database_<db>_check_point_duration` → интервал | `du -sh /var/lib/neo4j/data/transactions/` растёт | Поднять `db.checkpoint.iops.limit`, перейти на `CONTINUOUS` (EE) |
| **Репликация встала** | `changes(last_committed_tx_id[5m]) == 0` | Логи кластера, `neo4j_database_<db>_cluster_raft_is_leader` | Проверить сеть между кластерными узлами, перезапустить follower |
| **Query.log слишком большой** | Диск заполняется `query.log*` | `du -sh /var/log/neo4j/query.log*` | Переключить `db.logs.query.enabled=INFO`, задать `db.logs.query.threshold=100ms` |
| **JMX порт открыт наружу** | Порт 3637 доступен из сети | `nmap -p 3637 <host>` | Закрыть firewall, слушать только localhost, отключить `server.metrics.jmx.enabled=false` |
| **CSV метрики не пишутся** | Папка `/var/lib/neo4j/metrics` пуста | `server.metrics.csv.enabled=true`, права на папку | Проверить `server.directories.metrics`, права пользователя `neo4j` |
| **Алерты не срабатывают** | Правила есть, но алертов нет | `promtool check rules`, `promtool test rules` | Проверить `for` duration, labels, `scrape_interval` ≤ `for` |

## Ограничения и крайние случаи

- **Community Edition:** нет Prometheus endpoint, `query.log`, `security.log`, `CONTINUOUS`/`VOLUMETRIC` checkpoint. Только JMX, CSV, `debug.log`, `neo4j.log`.
- **Метрики кластера:** `last_committed_tx_id` и `cluster_raft_is_leader` имеют смысл только в кластере. На standalone всегда `1` и монотонно растущий ID.
- **Кардинальность метрик:** В мультидатабазовых инстансах каждая база добавляет свою серию `neo4j_database_<db>_*`. При 50+ базах может превыситься `sample_limit` Prometheus.
- **`dbms.page_cache.hit_ratio` vs `database.<db>.page_cache.hit_ratio`:** DBMS-уровень усредняет по всем базам. Падение на одной маской базах может быть невидимым. Обязательно мониторьте per-database.
- **`bolt_thread_pool_queue_size`:** Метрика доступна только в Enterprise Edition. В Community пул не ограничивается этой метрикой.
- **Prometheus endpoint security:** Порт 2004 не имеет аутентификации, TLS, rate limiting. Никогда не открывайте наружу без reverse proxy с mTLS.
- **JMX RCE вектор:** `server.metrics.jmx.enabled=true` (default) открывает порт 3637. Обязательно закрывайте на сетевом уровне.
- **GC логи и Log4j:** GC логи не управляются Log4j — они настраиваются через `server.jvm.additional`. Параметры `server.logs.gc.*` касаются только ротации файла, который пишет JVM.
- **Clock skew в кластере:** `last_committed_tx_id` сравнивается между узлами. При skew > 1s алерты репликации могут давать ложные срабатывания. Синхронизируйте время через `chrony`/`ntpd`.
- **Container memory limits:** `mem_limit` должен быть > `heap + page cache + 1GB OS`. Урезанный лимит не вызывает ошибку конфигурации — OOM Kill приходит под нагрузкой.

## Лучшие практики

- **Версионируйте `neo4j.conf` в Git.** Конфигурация — часть состояния системы; воспроизводимость важнее удобства редактирования на месте.
- **Явно задавайте память.** Без явных `server.memory.*` Neo4j вычисляет значения сам при старте, результат меняется от версии к версии.
- **`initial_size = max_size` для heap.** Расхождение означает Full GC на каждом расширении кучи.
- **Отключайте `VERBOSE` на production.** `db.logs.query.enabled=INFO` с порогом даёт те же ответы при меньшем объёме.
- **Держите `query.log` и `security.log` включёнными.** Но `security.log` не в режиме «все успешные входы»: `dbms.security.log_successful_authentication=false`.
- **Не выставляйте эндпоинт метрик в сеть.** Порт 2004 не аутентифицирован. Используйте reverse proxy с TLS.
- **Включайте `debug.log` (JSON).** Нужен вендору при инцидентах, отключение не экономит ресурсов.
- **Мониторьте `usage_ratio`, не только `hit_ratio`.** `usage_ratio = 1.0` — сигнал расширять кэш ДО падения производительности.
- **Проверяйте алерты `promtool test rules`.** Синтаксическая валидация недостаточна — нужны юнит-тесты правил.
- **Используйте метаданные транзакций.** `tx.setMetaData({app: ..., type: ...})` кладёт в `query.log` имя приложения — поиск источника нагрузки становится точным.
- **CSV метрики сжимайте (ZIP).** Экономит диск, ускоряет чтение при разборе.
- **Файловые системы:** EXT4 с `noatime,nodiratime`. Разделяйте устройства для `data` и `transactions`.
- **Swap отключен на выделенном сервере.** Своп для Neo4j = катастрофическая деградация.

## См. также

- **[Обслуживание и эксплуатация](./operations.md)** — память, checkpointing, диагностика.
- **[Бэкап и восстановление](./backup_and_restore.md)** — процедуры резервного копирования Neo4j.
- **[Кластеризация и высокая доступность](./clustering.md)** — метрики и логи в кластере.
- **[Безопасность](./security.md)** — RBAC, TLS, обфускация логов.
- **[Драйверы](./drivers.md)** — `neo4j://`, пул соединений, наблюдаемость на стороне клиента.
- **[Нагрузочное тестирование](./performance_testing.md)** — как снимать те же метрики под нагрузкой.
- **[Диагностика на уровне JVM](./jvm_diagnostics.md)** — что стоит за метриками GC и heap.
- **[Метрики Neo4j](https://neo4j.com/docs/operations-manual/current/monitoring/metrics/reference/)** — полный справочник имён и порогов.
