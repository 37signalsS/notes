# ProxySQL: Query Rules и Query Cache

**Актуально для:** ProxySQL 3.0.11 (Stable) — последний стабильный релиз на 27 августа 2026 года (на момент обновления — октябрь 2026). Правила и кэш не менялись в 3.0.x; в 3.1.x (Innovative) появился TSDB и дополнительные колонки, но основные механизмы совместимы.

## Определения

| Термин | Значение |
| :--- | :--- |
| **Query Rule** | Правило в таблице `mysql_query_rules`, изменяющее маршрутизацию или поведение запроса |
| **Digest** | Нормализованный текст запроса без значений литералов; основной ключ группировки в статистике |
| **`match_digest`** | Сопоставление по нормализованному тексту запроса |
| **`match_pattern`** | Сопоставление по исходному тексту запроса регулярным выражением |
| **`negate_match_pattern`** | Инверсия `match_pattern`: `1` — правило срабатывает при **НЕ**совпадении regex |
| **`digest`** | Точное совпадение по конкретному digest (hex-значению из `stats_mysql_query_digest.digest`); колонка `mysql_query_rules.digest` |
| **`replace_pattern`** | Регулярное выражение для подстановки вместо исходного текста запроса (query rewrite) |
| **`re_modifiers`** | Модификаторы PCRE для regex в `match_pattern`/`match_digest`; по умолчанию `CASELESS` |
| **`flagIN`** | Входной флаг правила; набор битовых масок условий совпадения |
| **`flagOUT`** | Выходной флаг правила; переносит совпадение на следующие правила в цепочке |
| **`next_query_flagIN`** | Флаг, который становится `flagIN` для следующего запроса в сессии |
| **`mirror_flagOUT`** | Флаг, передаваемый в зеркальный hostgroup при `mirror_hostgroup` |
| **`apply`** | Флаг `1` означает «применить действие и остановить обработку», `0` — «продолжить» |
| **`mysql_query_rules_fast_routing`** | Таблица оптимизированного роутинга; позволяет пропустить основной движок правил для типовых случаев |
| **`mysql-query_processor_iterations`** | Число дополнительных проходов по правилам при `flagOUT`; по умолчанию `0` |
| **Query Cache** | TTL-кэш результатов в памяти ProxySQL |
| **Query Firewall** | Блокировка или перенаправление запросов правилами на уровне прокси |
| **`OK_msg`** | Текст, возвращаемый клиенту вместо выполнения запроса (запрос не уходит на бэкенд) |
| **`log`** | Флаг `0`/`1`: вести ли логирование запроса, прошедшего через правило, в Event Log |
| **`comment`** | Произвольный текстовый комментарий к правилу (для документирования) |
| **`attributes`** | JSON-объект с произвольными атрибутами правила; расширяемость для будущих фич |
| **`gtid_from_hostgroup`** | Hostgroup, откуда брать GTID для проверки консистентности при failover |
| **`sticky_conn`** | Флаг `0`/`1`: удерживать соединение с тем же бэкендом (пока не реализован в 3.0.x) |
| **`proxy_addr`** | Локальный IP-адрес, на котором прокси принимает соединение (для мульти-инстансных конфигураций) |
| **`proxy_port`** | Локальный порт, на котором прокси принимает соединение |

## Предварительные требования

Для работы с правилами нужен запущенный ProxySQL и доступ к Admin-интерфейсу (по умолчанию `127.0.0.1:6032`, пользователь `admin`/`admin`). Правила задаются через SQL-запросы к базе `main`, после чего загружаются в runtime командой `LOAD MYSQL QUERY RULES TO RUNTIME`.

**Что должно быть настроено до настройки правил:**

1. **Серверы в `mysql_servers`.** Правила указывают `destination_hostgroup`, и эти hostgroups должны существовать и содержать бэкенды. Пустой или несуществующий hostgroup приводит к ошибке при загрузке правил.
2. **Пользователи в `mysql_users`.** Правила с фильтром `username` работают только если пользователь есть в `mysql_users`. Правила без `username` применяются ко всем пользователям.
3. **Монитор бэкендов.** Если правила перераспределяют трафик между hostgroups, убедитесь, что `mysql-monitor_username` настроен и монитор проверяет бэкенды. Иначе бэкенды могут быть в статусе `OFFLINE_HARD` и не принимать трафик.
4. **Регулярные выражения.** Если используются `match_pattern`, убедитесь, что `mysql-query_processor_regex = 1` (включён по умолчанию в 3.0.x). Проверьте синтаксис через `SELECT 'test' REGEXP '^SELECT'` — PCRE-синтаксис, не POSIX.
5. **Digest vs. текст.** Если планируете использовать `match_digest`, сначала посмотрите реальный `digest_text` в `stats_mysql_query_digest`. Нормализованный текст не содержит чисел, строк в кавычках и прочих литералов — они заменены на `?`.

**Ограничения версии:**
- `mysql_query_rules_fast_routing` доступно во всех версиях 3.0.x.
- `attributes` (JSON) появился в 3.0.x; в более ранних версиях колонки нет.
- `sticky_conn` не реализован в 3.0.x — значение игнорируется.
- `gtid_from_hostgroup` работает только с включённым GTID-режимом на бэкендах.

## Теоретический блок

### Как устроен движок правил

ProxySQL — не SQL-совместимый движок. Это набор правил, применяемых последовательно. Поведение зависит от двух вещей, которые чаще всего понимают неверно.

**Первое: порядок применения — по убыванию `rule_id`.** Первым проверяется правило с наибольшим `rule_id`. Это контринтуитивно: `rule_id = 100` применяется раньше `rule_id = 1`.

**Второе: сопоставление условий — поразрядное (побитовое) сложение.** Все непустые условия правила объединяются операцией «и». Пустое условие считается «всегда истинным». Например:

```sql
-- Правило сработает, только если совпали ОБА условия:
-- username = 'app_reports' И schemaname = 'analytics'
INSERT INTO mysql_query_rules (rule_id, active, username, schemaname,
                               destination_hostgroup, apply)
VALUES (1000, 1, 'app_reports', 'analytics', 20, 1);
```

Следствие: нельзя задать «ИЛИ» через условия правила. Для множественных вариантов используются несколько правил с разными `rule_id` либо механизм цепочек через `flagOUT`.

### `match_digest` против `match_pattern`

Это два разных принципа сопоставления, и выбор влияет на производительность и устойчивость правил.

| Характеристика | `match_digest` | `match_pattern` |
| :--- | :--- | :--- |
| Что сравнивается | Нормализованный текст | Исходный текст запроса |
| Устойчивость к изменениям | Высокая: значения литералов не влияют | Низкая: любое изменение текста ломает правило |
| Подходит для | Роутинг по типу запроса | Тонкие условия, привязанные к синтаксису |
| Скорость | Выше | Ниже: требуется regex |

**Практическое правило:** `match_digest` — для роутинга и firewall, `match_pattern` — когда digest недостаточно. Regex работает через PCRE (`mysql-query_processor_regex = 1`).

### Числовые значения в regex

При сопоставлении `match_digest` регулярные выражения применяются к **нормализованному** тексту: числа заменены на `?`. Это часто становится источником ошибок:

```sql
-- Правильно: в digest нет числа
INSERT INTO mysql_query_rules (rule_id, active, match_digest, destination_hostgroup, apply)
VALUES (1001, 1, '^SELECT \* FROM orders WHERE customer_id = \?$', 20, 1);

-- Неправильно: в digest числа нет, правило никогда не сработает
-- VALUES (1002, 1, '^SELECT \* FROM orders WHERE customer_id = 42$', 20, 1);
```

Проверить фактический вид digest можно так:

```sql
SELECT digest, digest_text FROM stats_mysql_query_digest LIMIT 20;
# → digest     | digest_text
# → 0x7C1A...  | SELECT * FROM orders WHERE customer_id = ?
```

### `apply`: прерывание или продолжение обработки

`apply` определяет, завершается ли обработка на текущем правиле.

- `apply = 1` — действие правила применяется, дальнейшие правила **не** проверяются.
- `apply = 0` — действие применяется, обработка продолжается следующими правилами.

Значение по умолчанию `0` — частая причина того, что правило «не работает»: оно срабатывает, но следующее общее правило переопределяет его действие.

```sql
-- Правило требует apply = 1, иначе будет перекрыто общим правилом ниже
INSERT INTO mysql_query_rules (rule_id, active, match_digest, destination_hostgroup, apply)
VALUES (2000, 1, '^SELECT \* FROM audit_log', 30, 1);
```

### Цепочки правил: `flagIN`, `flagOUT`, `next_query_flagIN`

Один запрос может требовать нескольких независимых изменений, а `apply = 1` останавливает обработку. Цепочки решают это ограничение.

Механизм состоит из двух фаз:

1. **Первая фаза.** Правила с `flagIN = 0` (или без условия по флагам) обрабатываются обычным порядком. Совпавшее правило записывает свои флаги в `flagOUT`.
2. **Вторая фаза.** Правила с ненулевым `flagIN` проверяются на совпадение с накопленными флагами. Правило с `next_query_flagIN` может передать накопленные флаги дальше.

```sql
-- Правило 1: помечаем запрос флагом 1
INSERT INTO mysql_query_rules (rule_id, active, match_digest, flagOUT, apply)
VALUES (3000, 1, '^SELECT \* FROM reports\.', 1, 0);

-- Правило 2: реагирует на флаг 1 и задаёт маршрутизацию
INSERT INTO mysql_query_rules (rule_id, active, flagIN, destination_hostgroup, apply)
VALUES (3001, 1, 1, 20, 1);

-- Правило 3: дополнительно помечает флагом 2 и передаёт дальше
INSERT INTO mysql_query_rules (rule_id, active, flagIN, flagOUT, apply)
VALUES (3002, 1, 1, 2, 0);

-- Правило 4: реагирует на флаг 2 (через next_query_flagIN)
INSERT INTO mysql_query_rules (rule_id, active, next_query_flagIN, flagOUT, apply)
VALUES (3003, 1, 2, 2, 0);
```

**Критично:** вторая фаза выполняется только если `mysql-query_processor_iterations > 0`. Значение по умолчанию — `0`, то есть **механизм выключен**. Ошибка «правило с `flagIN` не срабатывает» почти всегда означает именно это.

```sql
UPDATE global_variables SET variable_value = '1'
WHERE variable_name = 'mysql-query_processor_iterations';
LOAD MYSQL VARIABLES TO RUNTIME;
SAVE MYSQL VARIABLES TO DISK;
```

### Оптимизированный роутинг (`mysql_query_rules_fast_routing`)

Основной движок правил выполняет полный перебор правил с проверкой каждого условия. Для типового production-нагрузки этого достаточно — правил обычно десятки, а не тысячи.

`mysql_query_rules_fast_routing` позволяет обработать частые случаи **до** основного движ�ка. Таблица заполняется автоматически из сохранённых правил при загрузке в runtime, вручную редактировать её не нужно. Ключевые колонки: `username`, `schemaname`, `flagIN`, `destination_hostgroup`, `mirror_flagOUT`.

```sql
SELECT username, schemaname, flagIN, destination_hostgroup, mirror_flagOUT
FROM runtime_mysql_query_rules_fast_routing;
# → username   | schemaname | flagIN | destination_hostgroup | mirror_flagOUT
# → app_oltp   | NULL       | 0      | 10                    | 0
```

| `mysql-query_rules_fast_routing_algorithm` | Поведение |
| :--- | :--- |
| `1` (по умолчанию) | Hashtable на поток; ниже contention, больше расход памяти |
| `2` | Общая hashmap на все потоки; меньше памяти, выше contention |

**Практический вывод:** включать fast routing стоит, только если правил действительно много (сотни и более) и профилирование показало накладные расходы движка правил. Для десятков правил выигрыша нет.

### Throttling через `delay` и `timeout`

Правила могут ограничивать скорость и время выполнения запроса.

```sql
-- Искусственная задержка перед выполнением
-- Полезно для сглаживания пиковой нагрузки на отчётах
INSERT INTO mysql_query_rules (rule_id, active, username, delay, apply)
VALUES (4000, 1, 'app_reporting', 500, 1);

-- Ограничение времени выполнения запроса, мс
INSERT INTO mysql_query_rules (rule_id, active, match_digest, timeout, apply)
VALUES (4001, 1, '^SELECT .* FROM big_report', 30000, 1);

-- Число повторов при ошибке, максимум 1000
INSERT INTO mysql_query_rules (rule_id, active, schemaname, retries, apply)
VALUES (4002, 1, 'analytics', 3, 1);
```

| Параметр | Тип | Назначение |
| :--- | :--- | :--- |
| `delay` | Мс | Задержка перед отправкой запроса на бэкенд |
| `timeout` | Мс | Максимальное время выполнения; `0` — не ограничено |
| `retries` | Целое, `0`–`1000` | Сколько раз повторить запрос при ошибке сервера |
| `reconnect` | `0`/`1` | Попытаться переподключиться при разрыве соединения |

Значение `timeout` по умолчанию для всего ProxySQL задаётся переменной `mysql-default_query_timeout` (по умолчанию `86400000`, то есть 24 часа — фактически без ограничения).

### Query Firewall

Блокировка выполняется колонкой `error_msg`: запрос не уходит на бэкенд, клиент получает указанную ошибку.

```sql
-- Блокировка DDL
INSERT INTO mysql_query_rules (rule_id, active, match_digest, error_msg, apply)
VALUES (5000, 1, '^ALTER TABLE', 'DDL is not allowed through ProxySQL', 1);

-- Блокировка по пользователю
INSERT INTO mysql_query_rules (rule_id, active, username, error_msg, apply)
VALUES (5001, 1, 'app_oltp', 'User is not allowed to run this query', 1);

-- Блокировка по схеме
INSERT INTO mysql_query_rules (rule_id, active, schemaname, error_msg, apply)
VALUES (5002, 1, 'mysql', 'Access to system schema is denied', 1);

LOAD MYSQL QUERY RULES TO RUNTIME;
SAVE MYSQL QUERY RULES TO DISK;
```

**Ограничение firewall:** блокировка происходит **после** парсинга запроса, но **до** отправки на бэкенд. Она не защищает от DoS на этапе парсинга и не ограничивает длину самого запроса. Для защиты от дорогостоящих регулярных выражений и больших запросов нужен сетевой уровень.

**Практическое ограничение правил по длине:** правила не имеют регулировки числа совпадений. Если одно правило соответствует сотням тысяч запросов в секунду, его стоит вынести в fast routing.

### Query Cache

Кэш ProxySQL — это TTL-кэш в памяти, **не связанный** с `query_cache` MySQL и не имеющий инвалидации.

| Параметр | Где задаётся | Назначение |
| :--- | :--- | :--- |
| `mysql-query_cache_size_MB` | Глобальная переменная | Размер кэша в МБ; по умолчанию `256` — кэш **включён из коробки**. Установка в `0` или `NULL` отключает кэш |
| `mysql-query_cache_soft_ttl_pct` | Глобальная переменная | «Мягкий» TTL в процентах от `cache_ttl`: достигнув его, запись перестаёт попадать в кэш и обновляется с бэкенда. `0`–`100`, по умолчанию `0` |
| `mysql-query_cache_handle_warnings` | Глобальная переменная | Обрабатывать ли предупреждения MySQL как ошибку кэширования; по умолчанию `0` |
| `cache_ttl` | Колонка правила | Время жизни записи, мс |
| `cache_timeout` | Колонка правила | Сколько мс ждать ответа бэкенда перед отдачей устаревшего значения |
| `cache_empty_result` | Колонка правила | Кэшировать ли пустой результат |

```sql
-- Кэш уже активен по умолчанию: mysql-query_cache_size_MB = 256.
-- Явное включение (например, после отключения):
UPDATE global_variables SET variable_value = '128'
WHERE variable_name = 'mysql-query_cache_size_MB';
LOAD MYSQL VARIABLES TO RUNTIME;

-- Отключение кэша: значение 0 или NULL
UPDATE global_variables SET variable_value = 'NULL'
WHERE variable_name = 'mysql-query_cache_size_MB';
LOAD MYSQL VARIABLES TO RUNTIME;
SAVE MYSQL VARIABLES TO DISK;

-- Кэширование только неизменяемых справочников
INSERT INTO mysql_query_rules (rule_id, active, match_digest, cache_ttl, apply)
VALUES (6000, 1, '^SELECT .* FROM country_codes$', 3600000, 1);
LOAD MYSQL QUERY RULES TO RUNTIME;
SAVE MYSQL QUERY RULES TO DISK;
```

**Главное ограничение:** автоматической инвалидации при записи в таблицу **нет**. Запись перестаёт выдаваться только по истечении `cache_ttl`. Отсюда правило применения: кэшировать можно только то, что не меняется чаще TTL. Кэширование данных, изменяемых пользователями, приведёт к выдаче устаревших значений.

**Инвалидация вручную.** Прямого API для сброса кэша нет. Единственный способ принудительно освободить кэш — перезагрузка правил, которая сбрасывает все TTL-записи:

```sql
-- Принудительный сброс кэша: счётчики и TTL-записи обнуляются
LOAD MYSQL QUERY RULES TO RUNTIME;
```

**Мягкий TTL и single-flight.** При `mysql-query_cache_soft_ttl_pct > 0` «горячие» записи освежаются с бэкенда до истечения жёсткого TTL, а не отдаются клиенту устаревшими. В 3.0.11 добавлено `single-flight`-поведение при soft-TTL-обновлении: несколько одновременных запросов на одну и ту же устаревшую запись не посылают дублирующие запросы на бэкенд — один обновляет, остальные ждут. Это предотвращает кэш--thundering-хerd при включённом soft TTL.

### Зеркалирование запросов (`mirror_hostgroup`)

`mirror_hostgroup` отправляет копию запроса в другой hostgroup и возвращает клиенту ответ основного сервера.

```sql
-- Дублировать тяжёлые отчёты на выделенный сервер аналитики
INSERT INTO mysql_query_rules (rule_id, active, username, destination_hostgroup,
                               mirror_hostgroup, apply)
VALUES (7000, 1, 'app_bi', 20, 40, 1);
LOAD MYSQL QUERY RULES TO RUNTIME;
```

**Практическое предназначение:** тестирование новых запросов или миграция нагрузки — зеркальный hostgroup получает реальный трафик, не влияя на ответы клиентам.

**Ограничение:** зеркальный сервер не должен писать в те же данные. Иначе запрос выполнится дважды, что для операций записи неприемлемо.

### Полный перечень колонок `mysql_query_rules`

Схема таблицы (ProxySQL 3.0.11):

| Колонка | Тип | Назначение |
| :--- | :--- | :--- |
| `rule_id` | INTEGER PRIMARY KEY AUTOINCREMENT | Уникальный идентификатор; порядок применения — по убыванию |
| `active` | INT (0/1) | Активно ли правило |
| `username` | VARCHAR | Фильтр по пользователю; пусто = любой |
| `schemaname` | VARCHAR | Фильтр по схеме по умолчанию; пусто = любая |
| `client_addr` | VARCHAR | Фильтр по IP клиента; пусто = любой |
| `proxy_addr` | VARCHAR | Локальный IP, на котором прокси принимает соединение |
| `proxy_port` | INT | Локальный порт, на котором прокси принимает соединение |
| `flagIN` | INT >= 0 | Входной флаг цепочки |
| `flagOUT` | INT | Выходной флаг цепочки |
| `next_query_flagIN` | INT | Флаг для следующего запроса в сессии |
| `mirror_flagOUT` | INT | Флаг, передаваемый в зеркальный hostgroup |
| `mirror_hostgroup` | INT | Зеркальный hostgroup для копии запроса |
| `destination_hostgroup` | INT | Целевая группа хостов |
| `digest` | VARCHAR | Точное совпадение по digest (hex) |
| `match_digest` | VARCHAR | Regex по нормализованному тексту |
| `match_pattern` | VARCHAR | Regex по исходному тексту |
| `negate_match_pattern` | INT (0/1) | Инверсия `match_pattern`: `1` — правило срабатывает при НЕсовпадении |
| `re_modifiers` | VARCHAR | Модификаторы PCRE для regex; по умолчанию `CASELESS` |
| `replace_pattern` | VARCHAR | Подстановка вместо текста запроса (rewrite) |
| `reconnect` | INT (0/1) | Переподключаться при разрыве |
| `timeout` | INT UNSIGNED | Максимальное время выполнения, мс |
| `retries` | INT (0–1000) | Число повторов при ошибке |
| `delay` | INT UNSIGNED | Искусственная задержка перед выполнением, мс |
| `cache_ttl` | INT | Время жизни кэша, мс |
| `cache_timeout` | INT | Сколько ждать ответа бэкенда перед отдачей устаревшего значения |
| `cache_empty_result` | INT (0/1) | Кэшировать ли пустой результат |
| `error_msg` | VARCHAR | Текст ошибки при блокировке |
| `OK_msg` | VARCHAR | Текст, возвращаемый вместо выполнения (запрос не уходит на бэкенд) |
| `sticky_conn` | INT (0/1) | Удерживать соединение с бэкендом (колонка существует, но в 3.0.x не реализована — значение игнорируется) |
| `multiplex` | INT (0/1/2) | Управление мультиплексингом |
| `gtid_from_hostgroup` | INT | Hostgroup для GTID при failover |
| `log` | INT (0/1) | Логировать ли запрос в Event Log |
| `apply` | INT (0/1) | Прервать обработку после правила |
| `comment` | VARCHAR | Комментарий к правилу |
| `attributes` | VARCHAR (JSON) | Произвольные атрибуты правила |

**Практическое правило:** колонки `comment` и `attributes` — единственные, где можно описать назначение правила без влияния на поведение. Используйте их для документирования сложных цепочек.

## Практический блок

### Разделение чтения и записи

Базовый и самый полезный набор правил:

```sql
-- Читаемый пользователь направляется на реплики
INSERT INTO mysql_users (username, default_hostgroup, transaction_persistent, use_ssl)
VALUES ('app_reader', 20, 0, 0);
LOAD MYSQL USERS TO RUNTIME;

-- Записывающий пользователь направляется на writer
INSERT INTO mysql_users (username, default_hostgroup, transaction_persistent, use_ssl)
VALUES ('app_writer', 10, 0, 0);
LOAD MYSQL USERS TO RUNTIME;

-- Запросы чтения от writer-пользователя всё равно идут на реплики
INSERT INTO mysql_query_rules (rule_id, active, username, match_digest,
                               destination_hostgroup, apply)
VALUES (8000, 1, 'app_writer', '^SELECT', 20, 1);

-- Явное чтение с блокировкой всегда идёт на writer
INSERT INTO mysql_query_rules (rule_id, active, username, match_digest,
                               destination_hostgroup, apply)
VALUES (8001, 1, 'app_writer', '^SELECT .* FOR UPDATE', 10, 1);

-- Запись всегда на writer
INSERT INTO mysql_query_rules (rule_id, active, username, match_digest,
                               destination_hostgroup, apply)
VALUES (8002, 1, 'app_writer', '^(INSERT|UPDATE|DELETE|REPLACE)', 10, 1);
LOAD MYSQL QUERY RULES TO RUNTIME;
SAVE MYSQL QUERY RULES TO DISK;
```

> **Обратите внимание на `rule_id`.** Правило `8001` (специфичное, `FOR UPDATE`) имеет **больший** `rule_id`, чем правило `8000` (общее `SELECT`), поэтому применяется первым. Это не совпадение — правило должно иметь больший `rule_id`.

### Проверка срабатывания правил

```sql
-- Сколько раз каждое правило совпало.
-- ВАЖНО: счётчик сбрасывается при каждой загрузке правил в runtime,
-- в том числе при неявной синхронизации через ProxySQL Cluster.
SELECT rule_id, hits FROM stats_mysql_query_rules ORDER BY hits DESC;
# → rule_id | hits
# → 8001    | 15234
# → 8000    | 9845123
# → 8002    | 45231
```

**Нулевой `hits` означает одно из двух:** правило не срабатывает либо было только что загружено. Чтобы отличить второе от первого, проверьте условия правила и порядок:

```sql
-- Что именно приходит на вход: digest и пользователь
SELECT digest, digest_text, username, schemaname, hostgroup, count_star
FROM stats_mysql_query_digest
WHERE digest_text LIKE 'SELECT%FOR UPDATE%'
LIMIT 10;
# → digest_text                                  | username  | count_star
# → SELECT * FROM orders WHERE id = ? FOR UPDATE   | app_writer | 15234
```

Если `digest_text` в статистике отличается от шаблона в правиле — правило не совпадёт никогда.

### Проверка фактического digest для отладки

```sql
-- Брать digest, по которому хотим написать match_digest
SELECT digest, digest_text FROM stats_mysql_query_digest
WHERE count_star > 1000
ORDER BY count_star DESC
LIMIT 20;
# → digest     | digest_text
# → 0x7C1A...  | SELECT * FROM orders WHERE customer_id = ?
```

Практический приём: сначала посмотреть реальный `digest_text` в статистике, затем писать правило под него, а не под предполагаемый текст.

### Ограничение ресурсов для отчётов

```sql
-- Ограничить число одновременных соединений отчётного пользователя
UPDATE mysql_users SET max_connections = 20
WHERE username = 'app_reporting';
LOAD MYSQL USERS TO RUNTIME;

-- Ограничить время выполнения и добавить задержку для сглаживания пиков
INSERT INTO mysql_query_rules (rule_id, active, username, delay, timeout, apply)
VALUES (9000, 1, 'app_reporting', 200, 60000, 1);
LOAD MYSQL QUERY RULES TO RUNTIME;
SAVE MYSQL QUERY RULES TO DISK;
```

### Разбор проблемы «запрос не маршрутизируется»

```sql
-- 1. Есть ли совпадения у правила
SELECT rule_id, hits FROM stats_mysql_query_rules WHERE rule_id = 8001;
# → rule_id | hits
# → 8001    | 0        ← правило не срабатывает

-- 2. Какой реально digest у запроса
SELECT digest, digest_text, username, count_star
FROM stats_mysql_query_digest
WHERE count_star > 0
ORDER BY count_star DESC LIMIT 5;

-- 3. Действующее состояние правил в runtime
SELECT rule_id, active, match_digest, destination_hostgroup, apply
FROM runtime_mysql_query_rules
ORDER BY rule_id;
# → rule_id | active | match_digest                        | destination_hostgroup | apply
# → 8001    | 1      | ^SELECT .* FOR UPDATE               | 10                    | 1

-- 4. Не перекрывается ли правило более специфичным правилом с большим rule_id
SELECT rule_id, match_digest, username, destination_hostgroup
FROM runtime_mysql_query_rules
WHERE rule_id > 8001;
```

**Типичные причины в порядке частоты:**

1. Правило перекрыто другим правилом с большим `rule_id` и `apply = 1`.
2. `match_digest` не совпадает с реальным `digest_text` (в digest числа заменены на `?`).
3. Счётчик `hits` обнулён недавней загрузкой правил — проблемы нет.
4. `active = 0` в правиле.

### Устранение неполадок

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| Правило с `flagIN` не срабатывает | `mysql-query_processor_iterations = 0` по умолчанию | Установите `mysql-query_processor_iterations = 1` |
| Правило не применяется | Более специфичное правило с большим `rule_id` перекрывает его | Уменьшите `rule_id` специфичного правила или увеличьте приоритет |
| Regex не находит запрос | `match_digest` применён к тексту с числами | Проверьте реальный `digest_text` в `stats_mysql_query_digest` |
| Кэш возвращает устаревшие данные | TTL слишком большой, инвалидации нет | Уменьшите `cache_ttl`; для изменяемых данных не используйте кэш |
| Запросы блокируются не теми правилами | Условия складываются по И, а не ИЛИ | Разделите правила; используйте цепочки `flagOUT` |
| `hits = 0` у рабочего правила | Правила только что загружены в runtime | Подождите и проверьте повторно; счётчик сбрасывается при `LOAD` |
| Утечка памяти при большом числе правил | Тысячи правил обрабатываются для каждого запроса | Сократите число правил, включите fast routing |
| Правило с `delay` не даёт эффекта | Задержка применяется, но запрос уже в очереди | Проверьте фактическое время выполнения в `stats_mysql_query_digest` |
| `OK_msg` не возвращается | Запрос всё равно уходит на бэкенд | `OK_msg` работает только с `apply = 1`; проверьте, что предыдущие правила не перехватывают запрос |
| Запрос не логируется в Event Log | `log = 0` или Event Log выключен | Установите `log = 1` в правиле и включите `mysql-eventslog_default_log` |
| `replace_pattern` не изменяет текст | Regex не соответствует или `match_pattern` не задан | `replace_pattern` применяется к тексту, прошедшему `match_pattern`; проверьте оба поля |
| Правило с `multiplex = 1` не включает мультиплексинг | Транзакция или переменные клиента блокируют мультиплексинг | Ожидаемое поведение; `multiplex = 2` не отключает мультиплексинг для запросов с `@` |
| `mirror_hostgroup` дублирует запись | Зеркальный hostgroup пишет в те же таблицы | Ожидаемый риск; используйте зеркалирование только для чтения |
| `gtid_from_hostgroup` игнорируется | GTID не включён на бэкенде или `enforce_gtid_statement` = 0 | Включите GTID на всех бэкендах и в `mysql_users` |
| Правило с `comment` не отображается | Запрос к `runtime_mysql_query_rules` не включает колонку | `comment` доступен в `mysql_query_rules` и `runtime_mysql_query_rules` |

### Обслуживание и очистка

```sql
-- Удаление правила
DELETE FROM mysql_query_rules WHERE rule_id = 7000;
LOAD MYSQL QUERY RULES TO RUNTIME;
SAVE MYSQL QUERY RULES TO DISK;

-- Отключение правила без удаления (короче, чем DELETE)
UPDATE mysql_query_rules SET active = 0 WHERE rule_id = 7000;
LOAD MYSQL QUERY RULES TO RUNTIME;
SAVE MYSQL QUERY RULES TO DISK;

-- Полный откат правил к состоянию на диске
LOAD MYSQL QUERY RULES TO RUNTIME;

-- Сброс счётчиков совпадений
LOAD MYSQL QUERY RULES TO RUNTIME;
```

```sql
-- Удаление всех правил кэширования при отказе от кэша
DELETE FROM mysql_query_rules WHERE cache_ttl > 0;
LOAD MYSQL QUERY RULES TO RUNTIME;

-- Отключение кэша
UPDATE global_variables SET variable_value = 'NULL'
WHERE variable_name = 'mysql-query_cache_size_MB';
LOAD MYSQL VARIABLES TO RUNTIME;
SAVE MYSQL VARIABLES TO DISK;
```

**Правило безопасности:** перед удалением правил сохраняйте конфигурацию.

```sql
-- Дамп правил в файл для возможного восстановления
SELECT * FROM mysql_query_rules;
```

## Дополнительная информация

### См. также
- **[ProxySQL: Обзор](./proxysql_overview.md)** — архитектура и базовая настройка.
- **[ProxySQL: Транзакции и prepared statements](./proxysql_transactions.md)** — влияние транзакций на маршрутизацию.
- **[ProxySQL: Failover и мониторинг репликации](./proxysql_failover.md)** — hostgroups и маршрутизация при отказах.
- **[ProxySQL: Мониторинг](./proxysql_monitoring.md)** — анализ запросов через digest и eventslog.
- **[ProxySQL: Connection Pool и Multiplexing](./proxysql_connection_pool.md)** — влияние правил на мультиплексинг.

### Официальная документация
- [Query Rules](https://proxysql.com/documentation/rules/)
- [MySQL Tables — mysql_query_rules](https://proxysql.com/documentation/main-runtime/mysql-tables/)
- [Stats MySQL Query Rules](https://proxysql.com/documentation/the-admin-schemas/stats/stats-mysql-query_rules/)
- [FAQ: transaction_persistent disables routing](https://proxysql.com/documentation/faq/)