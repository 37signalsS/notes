# ProxySQL: Мониторинг

**Актуально для:** ProxySQL 3.0.11 (Stable) — последний стабильный релиз на август 2026 года.

## Определения

| Термин | Значение |
| :--- | :--- |
| **Встроенный exporter** | HTTP-эндпоинт метрик ProxySQL, реализованный как REST API admin-интерфейса |
| **`admin-restapi_enabled`** | Переменная, включающая встроенный exporter |
| **`admin-restapi_port`** | Порт встроенного exporter; по умолчанию `6070` |
| **`admin-prometheus_memory_metrics_interval`** | Интервал сбора метрик памяти (jemalloc), с; по умолчанию `61` |
| **Admin Interface** | Интерфейс управления ProxySQL на порту `6032`; не является источником метрик |
| **HTTP Web Server** | Встроенный веб-интерфейс с визуализацией метрик; включается через `admin-web_enabled`, порт `6080` |
| **TSDB (Embedded Time-Series Database)** | Встроенная база временных рядов для хранения исторических метрик; доступна с 3.1.x (в 3.0.x — без TSDB) |
| **Digest** | Нормализованный текст запроса; ключ группировки в статистике |
| **`stats_mysql_query_digest`** | Таблица агрегированной статистики запросов |
| **`stats_proxysql_global`** | Таблица глобальных метрик ProxySQL (появилась в 3.0.7); TLS-configuration state, load |
| **Event Log (eventslog)** | Журнал событий с текстом запросов, включаемый по требованию |
| **`stats_mysql_query_rules`** | Таблица счётчиков совпадения правил |
| **`mysql-long_query_time`** | Порог «долгого» запроса в мс; по умолчанию `1000` |
| **`stats_history`** | База исторических метрик; таблицы `history_mysql_query_digest`, `mysql_connections`, `mysql_query_cache`, `system_cpu`, `system_memory` и др. |

## Теоретический блок

### Встроенный exporter вместо внешнего

ProxySQL имеет встроенный HTTP-эндпоинт для метрик. Отдельный `proxysql-exporter` устанавливать **не требуется**.

Механизм основан на REST API admin-интерфейса. Это важное различие:

| Компонент | Порт | Назначение |
| :--- | :--- | :--- |
| Admin Interface | `6032` | SQL-доступ для управления конфигурацией и чтения stats-таблиц |
| Встроенный exporter | `6070` | HTTP-эндпоинт `/metrics` для Prometheus |

**Exporter выключен по умолчанию.** Метрики не отдаются, пока не задано `admin-restapi_enabled = true`. Это частая причина «ProxySQL не отдаёт метрики» — endpoint просто не запущен.

**Дополнительный нюанс:** REST API администрирования появился в ProxySQL 2.4.0. Для более ранних версий, если требуется именно REST-управление, встроенного экспортера нет.

### HTTP Web Server и TSDB: альтернативы Prometheus

Помимо Prometheus-экспортера, ProxySQL предоставляет два дополнительных механизма мониторинга.

#### Встроенный веб-интерфейс (HTTP Web Server)

Встроенный HTTP-сервер предоставляет визуальный интерфейс для мониторинга состояния прокси в реальном времени. Он **отключён по умолчанию** и включается переменной `admin-web_enabled`.

| Переменная | По умолчанию | Смысл |
| :--- | :--- | :--- |
| `admin-web_enabled` | `false` | Включить веб-сервер |
| `admin-web_port` | `6070` | Порт веб-сервера (по умолчанию совпадает с exporter-портом) |
| `admin-web_verbosity` | `0` | Уровень детализации отладочного вывода (0–10) |

> **Важно:** веб-сервер использует учётные записи из `admin-stats_credentials` (пары `user:password`, разделённые точкой с запятой). По умолчанию доступен пользователь `stats` с паролем `stats`.

Интерфейс предоставляет следующие страницы:

| Страница | Содержание |
| :--- | :--- |
| **Connection Pool** | Детализированный разбор соединений по hostgroup и серверам (Used, Free, OK, Errors) |
| **Query Digest** | Реальный вид самых частых запросов и их метрик |
| **System Stats** | CPU и потребление памяти процесса ProxySQL |
| **Processlist** | Активные клиентские соединения и их состояние |

#### Встроенная база временных рядов (TSDB)

TSDB (Embedded Time-Series Database) — встроенная база временных рядов для хранения исторических метрик. Доступна начиная с ProxySQL **3.1.x (Innovative tier)**; в 3.0.x (Stable) отсутствует. Позволяет хранить метрики внутри ProxySQL без внешней базы данных и строить графики через веб-интерфейс.

**Ключевые особенности:**
- Вставка, обнаружение и даунсэмплирование метрик координируют доступ к общей SQLite-соединению (в 3.1.11 устранены race conditions при `SQLITE_BUSY`).
- Часовой ротационный механизм не конфликтует с обнаружением метрик и вставкой данных.
- Для 3.0.x альтернативой служит база `stats_history` (см. ниже).

#### Метрики памяти и `stats_proxysql_global`

| Метрика / таблица | Описание |
| :--- | :--- |
| `stats_memory_metrics` | Метрики памяти: `jemalloc_allocated`, `jemalloc_active`, `jemalloc_mapped`, `jemalloc_resident`, `SQLite3_memory_bytes`, `query_digest_memory`, `stack_memory_mysql_threads` и др. |
| `stats_proxysql_global` | Глобальные метрики ProxySQL (появилась в 3.0.7): состояние TLS-конфигурации, нагрузка, не привязанные к конкретному протоколу показатели |
| `admin-prometheus_memory_metrics_interval` | Интервал сбора метрик памери (секунды); по умолчанию `61`. Метрики памяти собираются по собственному таймеру, а не «по требованию» при скрапе — это единственная группа метрик с внутренним циклом сбора |

**Особенность сбора:** большинство метрик обновляются «по требованию» — внутренние счётчики собираются и экспортируются при каждом запросе к `/metrics`. Это обеспечивает минимальную нагрузку на ProxySQL при скрапинге. Метрики памяти — исключение: они собираются по циклу `admin-prometheus_memory_metrics_interval`.

**Рекомендация по интервалу скрапинга:** из-за природы метрик и потенциального роста числа временных серий, официальная документация **не рекомендует** субсекундные интервалы скрапинга. Типичный интервал — 15–30 с.

### Метрики: что нужно знать

Имена метрик, их типы и значения лейблов ниже приведены по исходному коду ProxySQL 3.0.11 (`lib/MySQL_HostGroups_Manager.cpp`, `lib/MySQL_Thread.cpp`, `lib/Query_Cache.cpp`), а не по документации. Это принципиально: набор экспортируемых метрик менялся между версиями, а документация описывает не полный набор.

В 3.0.11 каждая метрика дополнительно несёт лейбл `protocol` (`"mysql"` или `"pgsql"`). Он добавлен для устранения коллизий: модули MySQL и PostgreSQL регистрируют одноимённые метрики, и без лейбла они перезаписывали бы друг друга.

| Группа | Примеры (3.0.11) | Назначение |
| :--- | :--- | :--- |
| Клиентские соединения | `proxysql_client_connections_connected` (gauge), `proxysql_client_connections_total{status="created"\|"aborted"}` | Нагрузка на входе |
| Пул соединений | `proxysql_connpool_conns{status="used"\|"free"}` (gauge), `proxysql_connpool_conns_total{status="ok"\|"err"}`, `proxysql_connpool_conns_queries_total` | Состояние пула |
| Латентность пула | `proxysql_connpool_conns_latency_us` | Время установления соединения с бэкендом |
| Монитор | `proxysql_mysql_monitor_enabled`, `proxysql_mysql_monitor_ping_max_failures`, `proxysql_mysql_monitor_replication_lag_interval_seconds` | Доступность и роль монитора |
| Запросы | `proxysql_questions_total`, `proxysql_backend_query_time_seconds_total` (гистограмма), `proxysql_query_processor_time_seconds_total` | Производительность |
| Failover | `proxysql_backend_offline_during_query_total`, `proxysql_queries_with_max_lag_total` | Инциденты и задержки из-за лага |
| Транзакции | `proxysql_active_transactions`, `proxysql_com_commit_cnt_total`, `proxysql_com_rollback_total` | Нагрузка на записи |
| Query Cache | `proxysql_query_cache_count_get_total`, `proxysql_query_cache_count_set_total`, `proxysql_query_cache_entries_total` | Эффективность кэша |
| Внутренние | `proxysql_mysql_thread_workers`, `proxysql_mysql_max_connections`, `proxysql_mysql_wait_timeout` | Диагностика внутренних механизмов |

**Метрики пула различаются по статусу.** Метрика-счётчик `proxysql_connpool_conns_total` имеет лейбл `status` со значениями `ok` и `err`, а текущее состояние пула показывает gauge `proxysql_connpool_conns` со значениями `used` и `free`:

```promql
# Счётчик успешных и ошибочных попыток взять соединение из пула
proxysql_connpool_conns_total{status="ok"}
proxysql_connpool_conns_total{status="err"}

# Текущее состояние пула
proxysql_connpool_conns{status="used"}
proxysql_connpool_conns{status="free"}
```

Все эти метрики дополнительно помечены лейблами `endpoint="<host>:<port>"` и `hostgroup="<id>"`, поэтому их можно разложить по бэкендам: `proxysql_connpool_conns{status="free"}` по каждому `endpoint` показывает, у какого именно бэкенда пул исчерпан.

**Событие `SHUNNED` в метриках не отражается отдельной метрикой.** Внутренний статус соединения `SHUNNED` существует в stats-таблицах (`stats_mysql_connection_pool`), но в наборе метрик 3.0.11 для него нет отдельного значения лейбла. Если нужно отслеживать шуннинг, используйте stats-таблицу, а не метрики (см. [Stats-таблицы vs метрики](#stats-таблицы-vs-метрики)).

**Отдельной метрики для срабатывания query rules нет.** Счётчики совпадений правил хранятся в `stats_mysql_query_rules.hits`; чтобы вывести их в Prometheus, нужен `mysqld_exporter` с кастомным запросом к admin-интерфейсу, а не встроенный exporter.

**Не подставляйте имена метрик из устаревших руководств.** В сторонних примерах встречаются имена вроде `proxysql_connection_poolConnOK` или `proxysql_mysql_monitor_up`, которые встроенный exporter 3.0.11 не экспортирует. Единственный надёжный источник истинного набора — фактический вывод вашего инстанса:

```sql
SHOW PROMETHEUS METRICS;
```

Для агентов, которые читают старые метрики, альтернативой встроенному exporter служит сторонний проект [percona/proxysql_exporter](https://github.com/percona/proxysql_exporter) — он экспортирует данные из stats-таблиц и имеет собственную схему имён, не совпадающую с `proxysql_*` из встроенного exporter.

### Stats-таблицы vs метрики

Принципиальное различие: stats-таблицы дают **детализацию**, метрики — **агрегаты**.

| | Stats-таблицы | Prometheus-метрики |
| :--- | :--- | :--- |
| Доступ | SQL, admin-интерфейс `6032` | HTTP, `6070/metrics` |
| Детализация | До конкретного digest, сервера, сессии | Только агрегаты |
| Ограничение | Ручной запрос или внешний сборщик | Хранилище с временным рядом |
| Назначение | Разовый разбор, post-mortem | Постоянный мониторинг и алерты |

**Рабочий процесс:** Prometheus даёт сигнал «p99 вырос» → разбор идёт через stats-таблицы.

#### Верифицированные схемы stats-таблиц

Имена колонок ниже приведены по определениям в `include/ProxySQL_Admin_Tables_Definitions.h` (ProxySQL 3.0.11). Это единственный надёжный источник: схема stats-таблиц не документирована в официальной документации и менялась между версиями. Полный набор таблиц можно получить на любом инстансе:

```sql
SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'stats_mysql%';
```

| Таблица | Колонки |
| :--- | :--- |
| `stats_mysql_connection_pool` | `hostgroup`, `srv_host`, `srv_port`, `status`, `ConnUsed`, `ConnFree`, `ConnOK`, `ConnERR`, `MaxConnUsed`, `Queries`, `Queries_GTID_sync`, `Bytes_data_sent`, `Bytes_data_recv`, `Latency_us` |
| `stats_mysql_processlist` | `ThreadID`, `SessionID`, `user`, `db`, `cli_host`, `cli_port`, `hostgroup`, `l_srv_host`, `l_srv_port`, `srv_host`, `srv_port`, `command`, `time_ms`, `info`, `status_flags`, `extended_info` |
| `stats_mysql_free_connections` | `fd`, `hostgroup`, `srv_host`, `srv_port`, `user`, `schema`, `init_connect`, `time_zone`, `sql_mode`, `autocommit`, `idle_ms`, `statistics`, `mysql_info` |
| `stats_mysql_query_digest` | `hostgroup`, `schemaname`, `username`, `client_address`, `digest`, `digest_text`, `count_star`, `first_seen`, `last_seen`, `sum_time`, `min_time`, `max_time`, `sum_rows_affected`, `sum_rows_sent` |
| `stats_mysql_global` | `Variable_Name`, `Variable_Value` |
| `stats_mysql_errors` | счётчики ошибок соединений и запросов |

> **Обратите внимание на три расхождения с интуицией,** которые регулярно приводят к ошибкам в запросах:
> 1. В `stats_mysql_connection_pool` счётчики называются `ConnOK` / `ConnERR`, а не `srv_connections` / `srv_active_connections`.
> 2. В `stats_mysql_query_digest` колонка пользователя называется `username`, а в `stats_mysql_processlist` и `stats_mysql_free_connections` — `user`.
> 3. В `stats_mysql_processlist` длительность сессии — это `time_ms` (миллисекунды), а не `time_start_us`.

У каждой stats-таблицы (кроме `stats_mysql_global` и `stats_mysql_free_connections`) есть парная `_reset`-таблица с идентичной схемой, содержащая дельту с момента последнего сброса. Это позволяет считать прирост без внешнего хранилища:

```sql
SELECT r.hostgroup, r.digest, r.count_star AS delta_since_reset
FROM stats_mysql_query_digest_reset AS r
JOIN stats_mysql_query_digest AS d
  ON d.hostgroup = r.hostgroup AND d.digest = r.digest
WHERE r.count_star > 0
ORDER BY delta_since_reset DESC;
```

#### Исторические метрики: база `stats_history`

`stats_mysql_query_digest` — in-memory таблица: при перезапуске ProxySQL её содержимое пропадает. Для персистентного хранения исторических метрик служит база `stats_history`.

| Таблица | Назначение |
| :--- | :--- |
| `history_mysql_query_digest` | Дамп `stats_mysql_query_digest`, сохраняемый на диск |
| `mysql_connections` / `_day` / `_hour` | Статистика соединений с разной агрегацией |
| `mysql_query_cache` / `_day` / `_hour` | Метрики query cache |
| `myhgm_connections` / `_day` / `_hour` | Статистика Hostgroup Manager |
| `system_cpu` / `_day` / `_hour` | CPU нагрузка процесса ProxySQL |
| `system_memory` / `_day` / `_hour` | Использование памяти |

**Механизм:** содержимое `stats_mysql_query_digest` атомарно дампится в `stats_history.history_mysql_query_digest`, после чего `stats_mysql_query_digest` сбрасывается. Делается это по требованию или по расписанию. Подробности настройки — в официальной документации ProxySQL (раздел *Stats History Database*).

### Счётчики совпадения правил и их сброс

`stats_mysql_query_rules` содержит счётчик `hits` для каждого `rule_id`.

**Критично для интерпретации:** счётчик **обнуляется при каждой загрузке правил в runtime** — и при явной команде `LOAD MYSQL QUERY RULES TO RUNTIME`, и при неявной синхронизации через ProxySQL Cluster. Поэтому `hits = 0` не означает «правило не работает»: возможно, правила были перезагружены минуту назад.

Это делает `stats_mysql_query_rules` инструментом для **разбора в течение окна между перезагрузками**, а не для отслеживания накопленных срабатываний в долгую.

### Статистика по digest

`stats_mysql_query_digest` — основная таблица для анализа запросов.

Полезные колонки:

| Колонка | Смысл |
| :--- | :--- |
| `digest` | Хеш нормализованного запроса |
| `digest_text` | Нормализованный текст; числа заменены на `?` |
| `count_star` | Число выполнений |
| `sum_time` | Суммарное время выполнения, мкс |
| `hostgroup` | Hostgroup, в котором выполнялся запрос |
| `schemaname` | Схема |
| `username` | Пользователь |
| `first_seen` / `last_seen` | Первое и последнее появление |
| `cache_hit_count` | Число попаданий в query cache |

```sql
-- 10 самых тяжёлых запросов по суммарному времени
SELECT digest, digest_text, count_star,
       sum_time / 1000000 AS total_sec,
       sum_time / count_star / 1000 AS avg_ms
FROM stats_mysql_query_digest
ORDER BY sum_time DESC
LIMIT 10;
# → digest_text                                  | count_star | total_sec | avg_ms
# → SELECT * FROM events WHERE created_at > ?    | 45231      | 18234.5   | 403.2
```

**Ограничение:** `stats_mysql_query_digest` содержит агрегаты по нормализованному тексту. Различить два запроса, нормализованных до одинаковой формы, невозможно.

### Очистка статистики запросов

Таблица `stats_mysql_query_digest` растёт вместе с числом уникальных запросов. Без очистки она может занять значительную память. В 3.0.x очистка выполняется **административной командой**, а не настройкой порогов.

| Что | Механизм |
| :--- | :--- |
| Query digest | `PURGE TABLE stats_mysql_query_digest TO <timestamp>` — удаление по значению `last_seen` |
| Query Cache | Автоматически, по доле заполнения `mysql-query_cache_size_MB`; пороги заданы на этапе компиляции |

Переменных `mysql-purge_max_errors`, `mysql-purge_pct`, `mysql-purge_check_interval_min` и `mysql-purge_cached_errors` в 3.0.x **нет** — они существовали в ветке 1.x/2.x и встречаются в устаревших руководствах.

#### Очистка query digest

```sql
PURGE TABLE stats_mysql_query_digest TO <unix_timestamp>;
```

Удаляются все записи, у которых `last_seen` меньше указанного значения. Команда регистронезависима и принимает варианты `PURGE TABLE stats_mysql_query_digest TO`, `PURGE stats_mysql_query_digest TO`, а также префикс базы `stats.`; для PostgreSQL аналог — `stats_pgsql_query_digest`.

**Выбор значения `TO`:**

- `<текущее время минус срок хранения>` — удаляются только записи старше срока;
- `<заведомо будущее время>` — удаляются все записи;
- время раньше загрузки системы — команда возвращает успех, но ничего не удаляет: внутренний счётчик `last_seen` основан на монотонных часах.

#### Очистка Query Cache

Отдельный механизм, работающий по давлению памяти. Пороги заданы в коде как `constexpr` и **не настраиваются** через `global_variables`:

| Константа | Значение | Смысл |
| :--- | :--- | :--- |
| `purge_threshold_pct_min` | `3` | Ниже 3% заполнения кэш не очищается |
| `purge_threshold_pct_max` | `90` | Выше 90% очистка становится агрессивной |
| `purge_loop_time` | `500000` мкс | Интервал цикла очистки, 0.5 с |
| `purge_total_time` | `10000000` мкс | Полный интервал очистки, 10 с |

Практический вывод: единственный способ повлиять на вытеснение записей Query Cache — уменьшить или увеличить `mysql-query_cache_size_MB`. Настроить «держать не меньше 90% кэша» или «не вытеснять последние N записей» нельзя.

### Event Log: журнал с текстом запросов

Отдельный от digest журнал, сохраняющий **текст** каждого запроса.

| Переменная | По умолчанию | Смысл |
| :--- | :--- | :--- |
| `mysql-eventslog_default_log` | `0` | Логировать ли все запросы по умолчанию |
| `mysql-eventslog_format` | — | Формат записи |
| `mysql-eventslog_buffer_history_size` | `0` | Размер кругового буфера в событиях; `0` отключает |
| `mysql-eventslog_table_memory_size` | `10000` | Максимум событий в in-memory таблице |
| `mysql-eventslog_sync_buffer_to_disk` | `0` | Интервал автосброса буфера на диск, с |
| `mysql-eventslog_buffer_max_query_length` | без ограничения | Максимальная длина текста запроса в буфере |

**Круговой буфер в памяти** — ключевая особенность. Он не пишет на диск постоянно: при переполнении старые события вытесняются. Это позволяет вести детальный журнал без нагрузки на диск.

```sql
-- Включение буфера на 1 000 000 событий
SET mysql-eventslog_buffer_history_size = 1000000;
SET mysql-eventslog_default_log = 1;
LOAD MYSQL VARIABLES TO RUNTIME;
```

Сброс буфера в таблицу:

```sql
DUMP EVENTSLOG FROM BUFFER TO MEMORY;
SELECT query, COUNT(*) AS cnt
FROM stats_mysql_query_events
GROUP BY query ORDER BY cnt DESC LIMIT 10;
```

**Осторожно:** `mysql-eventslog_default_log = 1` логирует **все** запросы. На production-нагрузке это значительный расход CPU и памяти. Практичнее логировать по правилам:

```sql
-- Логировать только медленные запросы для пользователя
INSERT INTO mysql_query_rules (rule_id, active, username, log, timeout, apply)
VALUES (12000, 1, 'app_reporting', 1, 5000, 1);
LOAD MYSQL QUERY RULES TO RUNTIME;
```

Значение `log` в правиле: `1` — логировать, `0` — не логировать, `NULL` — применять глобальную настройку.

### Обнаружение медленных запросов

Порог задаётся глобальной переменной, а не настройкой бэкенда:

```sql
-- Порог в миллисекундах
SELECT variable_name, variable_value FROM global_variables
WHERE variable_name = 'mysql-long_query_time';
# → variable_value
# → 1000
```

Счётчик `Slow_queries` в `stats_mysql_global` растёт при превышении этого порога:

```sql
SELECT Questions, Slow_queries, Queries,
       (Slow_queries / Questions) * 100 AS slow_pct
FROM stats_mysql_global;
# → Questions | Slow_queries | Queries | slow_pct
# → 1548213   | 4821         | 1548213 | 0.311
```

## Практический блок

### Включение встроенного exporter

```sql
-- Включение и порт
UPDATE global_variables SET variable_value = 'true'
WHERE variable_name = 'admin-restapi_enabled';

UPDATE global_variables SET variable_value = '6070'
WHERE variable_name = 'admin-restapi_port';

LOAD ADMIN VARIABLES TO RUNTIME;
SAVE ADMIN VARIABLES TO DISK;
```

**Проверка:**

```bash
curl -s http://proxysql-host:6070/metrics | head -20
# → # HELP proxysql_client_connections_connected Client connections that are currently connected.
# → # TYPE proxysql_client_connections_connected gauge
# → proxysql_client_connections_connected{protocol="mysql"} 482
# → # HELP proxysql_connpool_conns How many backend connections are currently (free|used).
# → # TYPE proxysql_connpool_conns gauge
# → proxysql_connpool_conns{endpoint="10.0.0.1:3306",hostgroup="1",protocol="mysql",status="free"} 34
# → proxysql_connpool_conns{endpoint="10.0.0.1:3306",hostgroup="1",protocol="mysql",status="used"} 66
```

> **Важно:** в выводе присутствует лейбл `protocol`, поэтому любое правило Prometheus по этим метрикам должно его учитывать. Прямой запрос `proxysql_client_connections_connected` без указания лейблов вернёт все серии — для MySQL-инстанса это обычно единственная серия, но при активном модуле PostgreSQL их будет несколько.

```sql
SELECT variable_name, variable_value FROM global_variables
WHERE variable_name LIKE 'admin-restapi%';
# → variable_name       | variable_value
# → admin-restapi_enabled | true
# → admin-restapi_port    | 6070
```

> **Важно:** значения задаются через `LOAD ADMIN VARIABLES TO RUNTIME`, а не `LOAD MYSQL VARIABLES TO RUNTIME` — это разные группы переменных.

### Включение веб-интерфейса и TSDB (3.1.x)

```sql
-- Включение HTTP Web Server
UPDATE global_variables SET variable_value = 'true'
WHERE variable_name = 'admin-web_enabled';

-- Порт веб-интерфейса (по умолчанию 6070, совпадает с exporter)
UPDATE global_variables SET variable_value = '6070'
WHERE variable_name = 'admin-web_port';

-- Настройка учётных записей для веб-интерфейса и metrics endpoint
-- Пары user:password, разделённые точкой с запятой
UPDATE global_variables SET variable_value = 'stats:stats_pass;monitor:monitor_pass'
WHERE variable_name = 'admin-stats_credentials';

LOAD ADMIN VARIABLES TO RUNTIME;
SAVE ADMIN VARIABLES TO DISK;
```

**Проверка:**

```bash
curl -s http://proxysql-host:6070/ | head -5
# → <!DOCTYPE html>
```

**Аутентификация на metrics endpoint:** встроенный exporter использует учётные записи из `admin-stats_credentials`. Если переменная задана, доступ к `/metrics` требует Basic auth:

```bash
curl -u stats:stats_pass http://proxysql-host:6070/metrics | head -20
```

**Настройка Prometheus с аутентификацией:**

```yaml
scrape_configs:
  - job_name: 'proxysql'
    scrape_interval: 15s
    metrics_path: '/metrics'
    static_configs:
      - targets:
          - 'proxysql-1.example.com:6070'
          - 'proxysql-2.example.com:6070'
    relabel_configs:
      # Если есть Cluster, добавить метку с ролью узла
      - target_label: env
        replacement: production
    # Если admin-stats_credentials настроен, добавьте Basic auth:
    # basic_auth:
    #   username: 'stats'
    #   password: 'stats_pass'
```

**Проверка цели scrape:**

```bash
curl -s http://proxysql-host:6070/metrics | grep -c '^proxysql_'
# → 214
```

### Ключевые запросы для алертинга

#### Доступность и роли бэкендов

```promql
# MySQL Monitor выключен — failover и автоисключение бэкендов не работают
proxysql_mysql_monitor_enabled == 0

# Запросы, которые ушли на бэкенд, упавший в OFFLINE
rate(proxysql_backend_offline_during_query_total[5m]) > 0

# Запросы, задержанные из-за превышения replication_lag (max_lag)
rate(proxysql_queries_with_max_lag_total[5m]) > 0
```

> **Реального значения replication lag нет ни среди метрик, ни среди stats-таблиц, ни среди admin-команд.** Метрики монитора в 3.0.11 (`proxysql_mysql_monitor_replication_lag_interval_seconds`, `proxysql_mysql_monitor_ping_max_failures`, `proxysql_mysql_monitor_writer_is_also_reader` и другие) экспортируют **значения конфигурационных переменных**, а не результаты проверок. `proxysql_monitor_replication_lag_group_by_host` — тоже gauge конфиг-флага (группировать ли проверки лага по хостам), а не сам лаг. Перечень admin-команд (`SHOW MYSQL STATUS`, `SHOW PROMETHEUS METRICS`, `SHOW TSDB STATUS` и другие) не содержит команды, отдающей лаг, а stats-таблицы `stats_mysql_replication_hostgroups` в 3.0.11 не существует.
>
> Единственное место, где измеренный лаг доступен через SQL, — колонка `repl_lag` в базе `monitor`, таблица `mysql_server_replication_lag_log`. Это monitor-лог, а не stats-таблица и не метрика, поэтому во встроенный exporter он не попадает. Запрос к нему и ограничения приведены в [ProxySQL: Failover](./proxysql_failover.md#как-прочитать-измеренный-лаг).
>
> Практический вывод: для постоянного мониторинга лага надёжнее опрашивать бэкенд напрямую — `SHOW REPLICA STATUS` — через `mysqld_exporter`, подключённый к MySQL.

#### Пул соединений

```promql
# Ошибочные попытки взять соединение из пула
rate(proxysql_connpool_conns_total{status="err"}[5m]) > 0

# Исчерпание пула на конкретном бэкенде: свободных соединений нет
proxysql_connpool_conns{status="free"} == 0

# Запросы, упавшие на бэкенд, ушедший в OFFLINE
rate(proxysql_backend_offline_during_query_total[5m]) > 0
```

#### Производительность

```promql
# p99 времени выполнения запросов на бэкенде (секунды)
histogram_quantile(0.99, sum by (le) (rate(proxysql_backend_query_time_seconds_total_bucket{protocol="mysql"}[5m])))

# Доля ошибок протокола MySQL к общему числу запросов
rate(proxysql_mysql_error_total{protocol="mysql"}[5m]) / rate(proxysql_questions_total{protocol="mysql"}[5m]) > 0.01

# Рост клиентских соединений (возможная утечка)
deriv(proxysql_client_connections_connected[30m]) > 0

# Мультиплексирование перестало работать — соединений больше, чем запросов
rate(proxysql_myhgm_auto_increment_multiplex_total[5m]) == 0
  and rate(proxysql_client_connections_total{status="created"}[5m]) > 10
```

### Примеры правил алертинга

```yaml
groups:
  - name: proxysql
    rules:
      - alert: ProxySQLMonitorDisabled
        expr: proxysql_mysql_monitor_enabled == 0
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "MySQL Monitor в ProxySQL выключен — failover не произойдёт"

      - alert: ProxySQLConnectionPoolErrors
        expr: rate(proxysql_connpool_conns_total{status="err"}[5m]) > 0
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Ошибки пула соединений ProxySQL на хосте {{ $labels.endpoint }}"

      - alert: ProxySQLBackendOfflineDuringQuery
        expr: rate(proxysql_backend_offline_during_query_total[5m]) > 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "Запросы падают на бэкенд в OFFLINE — идёт failover"

      - alert: ProxySQLHighQueryLatency
        expr: histogram_quantile(0.99, sum by (le) (rate(proxysql_backend_query_time_seconds_total_bucket{protocol="mysql"}[5m]))) > 0.1
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "p99 времени запросов превышает 100ms"

      - alert: ProxySQLClientConnectionGrowth
        expr: deriv(proxysql_client_connections_connected[30m]) > 1
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "Устойчивый рост клиентских соединений — возможна утечка"
```

### Анализ нагрузки

#### Топ запросов по суммарному времени

```sql
SELECT digest_text, count_star,
       ROUND(sum_time / 1000000000, 2) AS total_sec,
       ROUND(sum_time / count_star / 1000, 2) AS avg_ms,
       ROUND(sum_time / (count_star * GREATEST(1, threads_running)) / 1000, 2) AS avg_ms_per_thread
FROM stats_mysql_query_digest
ORDER BY sum_time DESC
LIMIT 20;
# → digest_text                            | count_star | total_sec | avg_ms
# → SELECT * FROM events WHERE created_at>? | 45231      | 18234.5   | 403.2
```

#### Распределение запросов по hostgroups

```sql
SELECT hostgroup, COUNT(*) AS digests, SUM(count_star) AS queries
FROM stats_mysql_query_digest
GROUP BY hostgroup;
# → hostgroup | digests | queries
# → 10        | 124     | 452318
# → 20        | 892     | 1048213
```

**Ненулевое число запросов на writer-группе от read-only пользователя** — признак неверно настроенного роутинга.

#### Проверка активности правил

```sql
-- Внимание: счётчики сбрасываются при LOAD MYSQL QUERY RULES TO RUNTIME
SELECT r.rule_id, r.active, r.username, r.match_digest,
       r.destination_hostgroup, COALESCE(s.hits, 0) AS hits
FROM runtime_mysql_query_rules r
LEFT JOIN stats_mysql_query_rules s ON r.rule_id = s.rule_id
ORDER BY COALESCE(s.hits, 0) DESC
LIMIT 20;
# → rule_id | active | username  | match_digest        | destination_hostgroup | hits
# → 8000    | 1      | app_writer | ^SELECT             | 20                    | 984512
```

### Проверка состояния ProxySQL

```sql
-- Глобальные счётчики
SELECT uptime, Questions, Queries, Slow_queries,
       Client_Connections_connected, Client_Connections_aborted,
       Server_Connections_connected, Server_Connections_created,
       Queries_gtid_sync
FROM stats_mysql_global;
# → uptime | Questions | Slow_queries | Client_Connections_connected | Client_Connections_aborted
# → 86400  | 1548213   | 4821         | 482                         | 12
```

```sql
-- Соединения пула. Колонки: ConnOK / ConnERR — счётчики попыток,
-- ConnUsed / ConnFree — текущее состояние, MaxConnUsed — пик
SELECT hostgroup, srv_host, srv_port, status,
       ConnUsed, ConnFree, ConnOK, ConnERR, MaxConnUsed,
       Queries, Latency_us
FROM stats_mysql_connection_pool
ORDER BY hostgroup, srv_host;
```

```sql
-- Активные сессии. extended_info заполняется для сессий,
-- удерживающих соединение к бэкенду ( pinning, транзакция, SET и т.п.)
SELECT SessionID, user, cli_host, cli_port, hostgroup,
       srv_host, srv_port, command, time_ms, status_flags, extended_info
FROM stats_mysql_processlist
WHERE extended_info IS NOT NULL AND extended_info != ''
ORDER BY time_ms DESC
LIMIT 20;
```

> **Колонка `status_flags`** — битовая маска внутренних флагов сессии (в том числе признак удержания соединения и признак multiplexing). Она же является источником метрики `proxysql_myhgm_auto_increment_multiplex_total`: если флаг multiplexing выставляется и снимается часто, счётчик переключений растёт.

> **Важно:** в `stats_mysql_processlist` нет колонок `username`, `client`, `server` и `time_start_us` — используйте `user`, `cli_host`/`cli_port`, `srv_host`/`srv_port` и `time_ms`. Полная схема таблицы приведена в [Stats-таблицы](#stats-таблицы).

```sql
-- Что именно удерживает соединение: free-соединения с признаком pinning
SELECT fd, hostgroup, srv_host, srv_port, user, schema, autocommit, idle_ms
FROM stats_mysql_free_connections
ORDER BY idle_ms DESC
LIMIT 20;
```

### Устранение неполадок

| Проблема | Причина | Решение |
| :--- | --- | :--- |
| Endpoint не отдаёт метрики | `admin-restapi_enabled` не включён | Установите переменную в `true`, выполните `LOAD ADMIN VARIABLES TO RUNTIME` |
| `Connection refused` на 6070 | Exporter выключен или задан другой порт | Проверьте `admin-restapi_enabled` и `admin-restapi_port` |
| Метрика не находится в Prometheus | Имя метрики отличается от ожидаемого | Сверьтесь с фактическим выводом `curl /metrics` |
| `hits = 0` у правила | Правила перезагружены, счётчик сброшен | Проверьте `LOAD MYSQL QUERY RULES TO RUNTIME`; подождите и повторите |
| `stats_mysql_query_digest` растёт | Очистка не выполняется или данных слишком много | Выполните `PURGE TABLE stats_mysql_query_digest TO <unix_timestamp>`; автоматической очистки в 3.0.x нет |
| В логах нет текста запросов | Event Log выключен | Включите `mysql-eventslog_buffer_history_size` и `mysql-eventslog_default_log` |
| Высокое потребление памяти | Включён лог всех запросов | Ограничьте логирование правилами вместо `mysql-eventslog_default_log = 1` |
| Event Log теряет старые события | Круговой буфер переполнен | Увеличьте `mysql-eventslog_buffer_history_size` либо чаще сбрасывайте `DUMP EVENTSLOG` |
| `Slow_queries` не растёт | Порог слишком высок для ваших запросов | Снизьте `mysql-long_query_time` |
| Метрики сходятся на разных узлах | Cluster не синхронизирует статистику | Ожидаемо; сравнивайте конфигурацию, а не счётчики |
| Метрики не отображаются в Prometheus | `admin-stats_credentials` задан, но аутентификация не настроена в Prometheus | Добавьте `basic_auth` в `scrape_config` или отключите `admin-stats_credentials` |
| Метрики памяти не обновляются | Интервал сбора `admin-prometheus_memory_metrics_interval` слишком большой | Уменьшите значение (по умолчанию `61` с) |
| Веб-интерфейс недоступен | `admin-web_enabled` не включён | Установите переменную в `true`, выполните `LOAD ADMIN VARIABLES TO RUNTIME` |
| TSDB не работает (3.1.x) | Используется версия 3.0.x | TSDB доступен только с 3.1.x; используйте `stats_history` или Prometheus |
| `SHOW TSDB STATUS` неизвестна | Используется ProxySQL 3.0.x | Команда появилась в 3.1.x; в 3.0.x TSDB нет |
| Метрики не попадают в TSDB | Метрики собираются «по требованию», а не циклически | Используйте Prometheus для постоянного сбора; TSDB — для локального хранения |

### Обслуживание и очистка

```sql
-- Очистка статистики запросов после завершения разбора
DELETE FROM stats_mysql_query_digest;

-- Очистка счётчиков правил (мягкий сброс без перезагрузки конфигурации)
DELETE FROM stats_mysql_query_rules;

-- Очистка журнала ошибок
DELETE FROM stats_mysql_errors;

-- Очистка prepared statements
DELETE FROM stats_mysql_prepared_statements_info;
```

```sql
-- Удалить записи query digest, не обновлявшиеся дольше суток.
-- Значение TO — Unix-таймстемп в секундах: подставьте «сейчас минус 86400».
PURGE TABLE stats_mysql_query_digest TO 1767225600;

-- Проверка: было / стало
SELECT COUNT(*) FROM stats_mysql_query_digest;
```

Очистка Query Cache отдельно не настраивается — она происходит автоматически по мере заполнения. Единственный рычаг — значение `mysql-query_cache_size_MB`.

```bash
# Ротация логов ProxySQL
ls -la /var/log/proxysql/
# → proxysql.log

# Проверка размера базы данных ProxySQL (SQLite)
du -sh /var/lib/proxysql/
```

### Очистка исторических метрик (stats_history)

Метрики в `stats_history` накапливаются на диске. Очистка выполняется вручную:

```sql
-- Очистка истории запросов старше N дней
DELETE FROM stats_history.history_mysql_query_digest
WHERE last_seen < strftime('%s', 'now', '-30 days');

-- Очистка истории соединений
DELETE FROM stats_history.mysql_connections_day
WHERE time_start_us < (strftime('%s', 'now', '-30 days') * 1000000);

-- Проверка размера базы
SELECT COUNT(*) FROM stats_history.history_mysql_query_digest;
```

**Рекомендация:** на production-инстансах настройте периодическую очистку `stats_history` по расписанию (cron), чтобы избежать роста `proxysql.db`.

### Резервное копирование конфигурации

```bash
# Резервное копирование базы данных ProxySQL (SQLite)
cp /var/lib/proxysql/proxysql.db /var/lib/proxysql/proxysql.db.$(date +%Y%m%d)

# Проверка целостности базы
sqlite3 /var/lib/proxysql/proxysql.db "PRAGMA integrity_check";
```

## Дополнительная информация

### См. также
- **[ProxySQL: Обзор](./proxysql_overview.md)** — архитектура и базовая настройка.
- **[ProxySQL: Connection Pool и Multiplexing](./proxysql_connection_pool.md)** — метрики пула и их интерпретация.
- **[ProxySQL: Failover и мониторинг репликации](./proxysql_failover.md)** — монитор, SHUNNED, журналы проверок.
- **[ProxySQL: Query Rules и Query Cache](./proxysql_query_rules.md)** — правила, их счётчики и журнал.
- **[Мониторинг баз данных](../monitoring.md)** — общий контекст мониторинга БД.
- **[Prometheus: Обзор](../../../Prometheus/overview.md)** — настройка Prometheus и алертинга.

### Официальная документация
- [Prometheus Metrics](https://proxysql.com/documentation/prometheus-exporter/) — встроенный exporter, переменные, рекомендации по скрапингу.
- [HTTP Web Server](https://proxysql.com/documentation/http-web-server/) — веб-интерфейс, dashboard, аутентификация.
- [Embedded Time-Series Database (TSDB)](https://proxysql.com/documentation/embedded-time-series-database/) — встроенная база временных рядов (3.1.x+).
- [Stats History Database](https://proxysql.com/documentation/the-admin-schemas/stats-history/) — персистентное хранение метрик.
- [Query Logging](https://proxysql.com/documentation/query-logging/) — журнал запросов.
- [Advanced Event and Query Logging](https://proxysql.com/documentation/advanced-event-and-query-logging/) — Event Log, круговой буфер.
- [Stats MySQL](https://proxysql.com/documentation/the-admin-schemas/stats/stats-mysql/) — схемы stats-таблиц.
- [Admin Variables](https://proxysql.com/documentation/global-variables/admin-variables/) — админ-переменные, включая `admin-restapi_*`, `admin-web_*`.