# ProxySQL: Транзакции и Prepared Statements

**Актуально для:** ProxySQL 3.0.11 (Stable) / 3.1.11 (Innovative) — релизы от 27 августа 2026 года. Транзакции и мультиплексинг не менялись в 3.0.x/3.1.x; в 4.0.x (Plugin Chassis / AI Tier) добавлены MCP/GenAI фичи, не затронувшие этот функционал.

## Определения

| Термин | Значение |
| :--- | :--- |
| **Autocommit** | Режим MySQL, в котором каждый запрос выполняется как отдельная транзакция |
| **`transaction_persistent`** | Параметр пользователя в `mysql_users`: закреплять соединение за одним сервером на всю сессию |
| **Pinning (закрепление)** | Ситуация, когда клиентская сессия более не может использовать мультиплексинг и закрепляется за конкретным соединением пула |
| **Text protocol** | Протокол MySQL, в котором клиент подставляет значения в текст запроса через `mysql_real_escape_string` |
| **Binary protocol** | Протокол MySQL, в котором параметры prepared statement передаются отдельно от текста запроса |
| **`mysql-autocommit_false_is_transaction`** | Считать ли `autocommit=0` началом транзакции с точки зрения ProxySQL |
| **`mysql-autocommit_false_not_reusable`** | Требовать ли явного завершения транзакции перед повторным использованием соединения пула |
| **`mysql-enforce_autocommit_on_reads`** | Принудительно ли возвращать `autocommit=1` для клиентов, пришедших с `autocommit=0` |
| **Sticky session** | Закрепление сессии за сервером через `sticky_conn` в правиле |
| **`mysql-multiplexing`** | Глобальный выключатель мультиплексинга; `true` по умолчанию |
| **`mysql-keep_multiplexing_variables`** | Список имён переменных, опрос которых **не** отключает мультиплексинг (по умолчанию `tx_isolation,version`) |
| **`mysql-set_query_lock_on_hostgroup`** | Что делать, если `SET`-запрос не распарсен: `1` — блокировать мультиплексинг **и** маршрутизацию, `0` — оставить поведение по умолчанию |
| **`mysql_query_rules.multiplex`** | Колонка правила: `0` — отключить мультиплексинг для запроса, `1` — включить, `2` — не отключать (например, для `SELECT @@var`) |
| **`mysql-session_track_variables`** | В v3.0.8+ включает нативное отслеживание сессионных переменных на бэкенде (режимы `0`/`1`/`2`) |
| **`mysql-default_isolation_level`** | Устарел с 2.0.11; заменён `mysql-default_tx_isolation` |
| **`mysql-default_tx_isolation`** | Устарел с 2.1.1; уровень изоляции задаётся только на сессионном уровне |
| **`mysql-default_transaction_read`** | Устарел с 2.0.11; режим чтения/записи транзакции |
| **`mysql-forward_autocommit`** | Устарел с 2.1.1; если `true`, `SET autocommit=0` пересылается на бэкенд |
| **`mysql-default_sql_mode`** | Устарел с 2.0.11; ProxySQL предполагает, что все бэкенды имеют этот `sql_mode` |
| **`mysql-default_time_zone`** | Устарел с 2.0.11; часовой пояс по умолчанию для подключений |
| **`mysql-default_schema`** | Схема по умолчанию для клиентов, не указавших её; `information_schema` |

## Базовые концепции

### Почему транзакции ломают мультиплексинг

Мультиплексинг предполагает, что между двумя последовательными запросами клиента в соединении пула нет незавершённого состояния. Транзакция нарушает это предположение: между `BEGIN` и `COMMIT` соединение находится в состоянии, которое принадлежит конкретной сессии.

Если бы ProxySQL отдал соединение пула с открытой транзакцией другой сессии, вторая сессия увидела бы незавершённую транзакцию и работала бы с изоляцией, которой не ожидала. Поэтому при `BEGIN` ProxySQL прекращает мультиплексирование и **закрепляет** сессию за этим соединением до `COMMIT`/`ROLLBACK`.

Отсюда прямое следствие для проектирования: **приложение, которое держит транзакции постоянно, теряет выигрыш от мультиплексирования.** Размер пула в этом случае должен быть близок к числу одновременных транзакций, а не определяться экономией соединений.

### Autocommit и состояние соединения

Поведение определяется четырьмя взаимосвязанными переменными:

| Переменная | По умолчанию | Смысл |
| :--- | :--- | :--- |
| `mysql-autocommit_false_is_transaction` | `false` | Считать ли сессию с `autocommit=0` находящейся в транзакции |
| `mysql-autocommit_false_not_reusable` | `false` | Запрещать повторное использование соединения пула, пока `autocommit=0` |
| `mysql-enforce_autocommit_on_reads` | `false` | Возвращать ли клиенту `autocommit=1`, если он пришёл с `autocommit=0` |
| `mysql-forward_autocommit` | `false` (устарел с 2.1.1) | Если `true`, `SET autocommit=0` пересылается на бэкенд; если `false` — ProxySQL отслеживает значение и меняет его на бэкенде при необходимости |

**Значение по умолчанию `false` у всех трёх означает:** клиент, выполнивший `SET autocommit=0` (что делают многие ORM и фреймворки), **не считается** ProxySQL находящимся в транзакции. Сессия продолжает мультиплексироваться.

Это компромисс: он сохраняет мультиплексинг, но означает, что весь SQL, отправленный с `autocommit=0`, реально выполняется с `autocommit=1` на бэкенде. Если приложение полагается на неявную транзакцию, поведение будет неверным.

**Когда включать `mysql-autocommit_false_is_transaction = 1`:**

- приложение явно полагается на `autocommit=0` как на «всё в одной транзакции»;
- корректность важнее экономии соединений.

**Цена:** сессии с `autocommit=0` теряют мультиплексинг, и пул должен быть расширен.

**Рекомендация по `mysql-forward_autocommit`:** оставьте `false` (дефолт). При `true` `SET autocommit=0` пересылается на бэкенд, но сам по себе не запускает транзакцию — соединение возвращается в пул, и запросы могут выполниться на другом. Если включаете `true`, обязательно ставьте `mysql-autocommit_false_not_reusable=true`, иначе соединение вернётся в пул с `autocommit=0`.

### `transaction_persistent`: когда это правильное решение

`transaction_persistent` — параметр в таблице `mysql_users`. При значении `1` соединение клиента закрепляется за **одним сервером на всю сессию**.

**Что это даёт:**
- все запросы сессии попадают на один сервер;
- состояние сессии (временные таблицы, user variables, `LAST_INSERT_ID`, курсоры) согласовано;
- нет риска маршрутизации отдельных запросов на разные бэкенды.

**Чего это не даёт:**
- мультиплексинг для этого пользователя отключается полностью;
- рост числа соединений пула, пропорциональный числу одновременных сессий.

**Важное следствие:** при `transaction_persistent = 1` **query rules не применяются** к этому пользователю — маршрутизация зафиксирована на `default_hostgroup`. Это часто становится неожиданностью: правило для пользователя создано, а не работает.

```sql
-- Пользователь, которому нужна фиксированная сессия
INSERT INTO mysql_users (username, default_hostgroup, transaction_persistent, max_connections)
VALUES ('app_batch', 20, 1, 50);
LOAD MYSQL USERS TO RUNTIME;
SAVE MYSQL USERS TO DISK;
```

### `sticky_conn` как более тонкий вариант

`sticky_conn` в правиле закрепляет сессию за сервером, но работает на уровне правила, а не пользователя.

```sql
-- Только запросы этого пользователя к этой схеме закрепляются за сервером
INSERT INTO mysql_query_rules (rule_id, active, username, schemaname,
                               sticky_conn, apply)
VALUES (10000, 1, 'app_session', 'app', 1, 1);
LOAD MYSQL QUERY RULES TO RUNTIME;
```

**Когда применять:** когда мультиплексинг нужен для большинства трафика, но отдельные сессии требуют закрепления. Пользовательский `transaction_persistent` отключил бы мультиплексинг целиком, правило со `sticky_conn` — только для совпавших запросов.

### Prepared Statements

#### Два протокола — разные последствия

ProxySQL поддерживает оба протокола, но по-разному.

**Text protocol** (`mysql_real_query`): клиент сам подставляет значения в текст запроса с экранированием. Для ProxySQL это обычный запрос с готовым текстом — наименее эффективный вариант с точки зрения сети, но самый простой для прокси.

**Binary protocol** (`mysql_stmt_prepare` / `mysql_stmt_execute`): текст запроса передаётся один раз при `PREPARE`, затем `EXECUTE` передаёт только типы и значения параметров отдельно.

При этом ProxySQL **не является** обычным кэшем prepared statements бэкенда: он парсит подготовленный запрос и применяет к нему query rules, как к обычному запросу. Это и достоинство (маршрутизация работает), и источник сложности.

#### Что нужно знать про `PREPARE`/`EXECUTE`

Существенное различие между версиями:

- В ProxySQL 2.1 и старше текст и параметры prepared statements **разделены** при выполнении. Значит, правила роутинга применяются корректно, и значения параметров не попадают в `digest`.
- Соединение с незавершённым prepared statement **не мультиплексируется** — состояние подготовленного запроса принадлежит соединению.

#### Ограничения

| Ограничение | Следствие |
| :--- | :--- |
| Незавершённый prepared statement отключает мультиплексинг | Долгоживущие prepared statements снижают эффективность пула |
| `PREPARE` отправляется один раз, `EXECUTE` — многократно | Счётчики запросов могут не совпадать с ожиданием; смотрите `stats_mysql_prepared_statements_info` |
| Смена `hostgroup` приводит к потере prepared statements | При отключённом query cache запросы пересоздаются; при явном `DEALLOCATE PREPARE` клиент получит ошибку |
| Prepared statements в связке с `transaction_persistent` | Работает, но сессия закреплена за одним сервером |

**Отдельный флаг `MYSQL_FORWARD_STMT`, который фигурирует в части руководств, в актуальных версиях не требуется.** Если он указан в вашей конфигурации — это устаревшая практика.

### Таймауты транзакций

ProxySQL позволяет ограничить время жизни транзакции на уровне сессии:

| Переменная | По умолчанию | Смысл |
| :--- | :--- | :--- |
| `mysql-max_transaction_time` | `14400000` (4 часа) | Максимальная длительность транзакции, мс |
| `mysql-max_transaction_idle_time` | `14400000` (4 часа) | Максимальное время простоя внутри транзакции, мс |
| `mysql-default_query_timeout` | `86400000` (24 часа) | Таймаут запроса по умолчанию |
| `mysql-default_query_delay` | `0` | Задержка по умолчанию |

**Практическое значение:** транзакция, зависшая на 4 часа из-за потерянного соединения, удерживает серверные ресурсы — блокировки, MVCC-версии, слоты в пуле. Значения по умолчанию слишком велики для production. Разумный выбор — десятки секунд для `max_transaction_idle_time`.

```sql
-- Разумные ограничения для OLTP-нагрузки
UPDATE global_variables SET variable_value = '60000'
WHERE variable_name = 'mysql-max_transaction_idle_time';

UPDATE global_variables SET variable_value = '30000'
WHERE variable_name = 'mysql-default_query_timeout';

LOAD MYSQL VARIABLES TO RUNTIME;
SAVE MYSQL VARIABLES TO DISK;
```

## Предварительные требования

Для работы с транзакциями и prepared statements в ProxySQL требуются:
- Запущенный ProxySQL 3.0.11+ (Stable) или 3.1.11+ (Innovative)
- Доступ к Admin-интерфейсу (по умолчанию `127.0.0.1:6032`, пользователь `admin`/`admin` из `admin-admin_credentials`)
- Настроенные бэкенды в `mysql_servers` с рабочим мониторингом
- Пользователи в `mysql_users` с соответствующими `default_hostgroup`
- Понимание того, как приложение управляет транзакциями (autocommit, BEGIN/COMMIT, prepared statements)

## Практический блок

### Диагностика транзакций в реальном времени

```sql
-- Активные транзакции
SELECT session_id, username, client, server, time_start_us,
       (time_now_us - time_start_us) / 1000000 AS duration_sec,
       extended_info
FROM stats_mysql_processlist
WHERE extended_info LIKE '%active transaction%'
ORDER BY duration_sec DESC;
# → session_id | username  | duration_sec | extended_info
# → 4821       | app_writer | 312          | [session] (1 active transactions)
```

**Поиск транзакций, удерживающих соединение пула:**

```sql
-- Сессии с транзакциями и их соединения
SELECT p.session_id, p.username, p.client, p.server,
       c.hostgroup, c.srv_host, c.status,
       (p.time_now_us - p.time_start_us) / 1000000 AS duration_sec
FROM stats_mysql_processlist p
JOIN stats_mysql_connection_pool c
  ON c.hostgroup = p.hostgroup
WHERE p.extended_info LIKE '%active transaction%'
LIMIT 20;
```

### Поиск prepared statements

```sql
-- Состояние prepared statements в ProxySQL
SELECT * FROM stats_mysql_prepared_statements_info LIMIT 20;
# → username  | schemaname | digest                          | global_stmt_id | stmt_id | num_execs
# → app_oltp  | app        | SELECT * FROM orders WHERE id=? | 4711            | 1       | 154821
```

**Оценка влияния на мультиплексинг:** большой `num_execs` при активном prepared statement означает, что соединение занято долго и мультиплексироваться не может.

### Проверка влияния autocommit на мультиплексинг

```sql
-- Сколько сессий закреплено из-за autocommit=0
SELECT extended_info, COUNT(*) AS sessions
FROM stats_mysql_processlist
WHERE extended_info IS NOT NULL AND extended_info != ''
GROUP BY extended_info
ORDER BY sessions DESC;
# → extended_info                     | sessions
# → [session] (1 active transactions) | 45
# → [session] (SET command)           | 128
```

Если после включения `mysql-autocommit_false_is_transaction = 1` число закреплённых сессий резко выросло — это ожидаемо и означает, что приложение активно использует `autocommit=0`. Нужно расширять пул, а не откатывать настройку.

### Настройка для транзакционного приложения

```sql
-- 1. Сессии приложения закрепляются за сервером
INSERT INTO mysql_users (username, default_hostgroup, transaction_persistent,
                         max_connections, use_ssl)
VALUES ('app_tx', 10, 1, 200, 0);
LOAD MYSQL USERS TO RUNTIME;

-- 2. Autocommit=0 считается транзакцией
UPDATE global_variables SET variable_value = '1'
WHERE variable_name = 'mysql-autocommit_false_is_transaction';

-- 3. Ограничение длительности транзакций
UPDATE global_variables SET variable_value = '30000'
WHERE variable_name = 'mysql-max_transaction_time';

UPDATE global_variables SET variable_value = '60000'
WHERE variable_name = 'mysql-max_transaction_idle_time';

LOAD MYSQL VARIABLES TO RUNTIME;
SAVE MYSQL USERS TO DISK;
SAVE MYSQL VARIABLES TO DISK;
```

**Проверка после настройки:**

```sql
SELECT variable_name, variable_value FROM global_variables
WHERE variable_name IN ('mysql-autocommit_false_is_transaction',
                        'mysql-max_transaction_time',
                        'mysql-max_transaction_idle_time');
# → variable_name                             | variable_value
# → mysql-autocommit_false_is_transaction      | 1
# → mysql-max_transaction_time                 | 30000
# → mysql-max_transaction_idle_time            | 60000
```

```sql
-- Пул должен быть расширен под фактическое число транзакций
SELECT hostgroup, srv_host, status, ConnUsed, ConnFree
FROM stats_mysql_connection_pool;
# → hostgroup | srv_host    | status | ConnUsed | ConnFree
# → 10        | db-writer-1 | ONLINE | 195      | 0
```

Значение `ConnUsed`, близкое к сумме `ConnUsed + ConnFree` (то есть `ConnFree ≈ 0`), подтверждает, что мультиплексинг при `transaction_persistent` не работает — это ожидаемо для транзакционного приложения.

### Транзакция, начавшаяся с чтения

Классическая проблема read/write split: транзакция открыта, первый запрос — `SELECT`, он ушёл на реплику, затем `UPDATE` внутри той же транзакции.

**Что происходит:** ProxySQL не переносит запрос внутри активной транзакции на другой сервер. Если `UPDATE` отправлен на реплику, он завершится ошибкой (`read-only`).

**Решения:**

```sql
-- Вариант 1: правило для SELECT ... FOR UPDATE с большим rule_id,
-- чтобы оно применялось раньше общего правила на реплики
INSERT INTO mysql_query_rules (rule_id, active, match_digest,
                               destination_hostgroup, apply)
VALUES (11000, 1, '^SELECT .* FOR UPDATE', 10, 1);

-- Вариант 2: маршрутизация всех запросов транзакционного пользователя на writer
INSERT INTO mysql_users (username, default_hostgroup, transaction_persistent)
VALUES ('app_tx', 10, 1);
```

**Практическое правило:** пользователям, выполняющим транзакции со смешанной нагрузкой чтения и записи, назначайте `default_hostgroup` = writer и `transaction_persistent = 1`. Экономия от мультиплексирования для них не работает в любом случае, а корректность важнее.

### Устранение неполадок

| Проблема | Причина | Решение |
| :--- | --- | :--- |
| `UPDATE` внутри транзакции возвращает read-only ошибку | `SELECT` ушёл на реплику, транзакция не переносится | Назначьте пользователя на writer с `transaction_persistent = 1` |
| Мультиплексинг перестал работать | Приложение держит транзакции или prepared statements | Смотрите `extended_info`; увеличьте пул под фактическое число сессий |
| Приложение получает `autocommit=1` вместо `0` | `mysql-enforce_autocommit_on_reads = 1` | Установите переменную в `0` |
| Query rules не применяются к пользователю | У пользователя `transaction_persistent = 1` | Роутинг зафиксирован; перенесите маршрутизацию в `default_hostgroup` |
| Транзакция «висит» часами | Значения таймаутов по умолчанию — 4 часа | Снизьте `mysql-max_transaction_idle_time` до десятков секунд |
| `Prepared statement not found` после смены hostgroup | Соединение переключилось, prepared statement потерян | Отключите query rules для этих запросов либо используйте `transaction_persistent` |
| Сессии закреплены, пул исчерпан | `mysql-autocommit_false_is_transaction` включён, приложение использует `autocommit=0` | Расширьте пул либо верните значение `0`, если корректность это допускает |
| Медленные транзакции блокируют запись | Длинные транзакции держат блокировки | Найдите через `stats_mysql_processlist` и сократите в приложении |

### Обслуживание и очистка

```sql
-- Проверка числа сессий, удерживаемых транзакциями
SELECT COUNT(*) AS pinned_by_transaction
FROM stats_mysql_processlist
WHERE extended_info LIKE '%active transaction%';

-- Поиск транзакций, выполняющихся дольше установленного порога
SELECT session_id, username, client, server,
       (time_now_us - time_start_us) / 1000000 AS duration_sec
FROM stats_mysql_processlist
WHERE (time_now_us - time_start_us) / 1000000 > 60;
```

```sql
-- Возврат к дефолтным значениям таймаутов
UPDATE global_variables SET variable_value = '14400000'
WHERE variable_name = 'mysql-max_transaction_time';

UPDATE global_variables SET variable_value = '14400000'
WHERE variable_name = 'mysql-max_transaction_idle_time';

LOAD MYSQL VARIABLES TO RUNTIME;
SAVE MYSQL VARIABLES TO DISK;

-- Снятие transaction_persistent с пользователя
UPDATE mysql_users SET transaction_persistent = 0 WHERE username = 'app_tx';
LOAD MYSQL USERS TO RUNTIME;
SAVE MYSQL USERS TO DISK;
```

**Важно:** снятие `transaction_persistent` возвращает мультиплексинг, но соединения клиентов должны переустановиться, чтобы настройка вступила в силу. Планируйте это в окно обслуживания.

## Edge Cases и ограничения

### Долгосрочные prepared statements и мультиплексинг

Приложения, использующие долгоживущие prepared statements (например, пулы соединений с кэшированием statement'ов на уровне драйвера), эффективно отключают мультиплексинг для этих соединений. Решение — использовать `transaction_persistent` для таких пользователей или ограничивать время жизни prepared statements на уровне приложения.

### Cross-hostgroup prepared statements (ProxySQL 3.0.10+)

Начиная с 3.0.10, ProxySQL корректно обрабатывает prepared statements, выполняемые на разных hostgroup'ах (исправлена ошибка #5895 — dangling bind buffers при смене hostgroup). Если вы используете старую версию, prepared statements в транзакциях должны выполняться строго в одном hostgroup.

### GTID и транзакции при failover

При использовании GTID-репликации и `gtid_from_hostgroup` в правилах, транзакция, начатая на старом writer'е, не будет автоматически перенесена на новый после failover. ProxySQL разорвёт соединение, и приложение получит ошибку. Приложение должно обрабатывать ошибки соединения и перезапускать транзакцию.

### `mysql-session_track_variables` и состояние сессии

С v3.0.8 переменная `mysql-session_track_variables` (режимы `0`/`1`/`2`) позволяет ProxySQL нативно отслеживать изменения сессионных переменных на бэкенде. Это уменьшает необходимость в `transaction_persistent` для сохранения состояния `sql_mode`, `time_zone` и других переменных, но не заменяет его полностью для временных таблиц и пользовательских переменных.

## Best Practices

1. **По умолчанию оставляйте `mysql-autocommit_false_is_transaction = false`** — это сохраняет мультиплексинг. Включайте только когда приложение действительно требует семантику `autocommit=0`.
2. **Используйте `transaction_persistent = 1` для батчевых/ETL-пользователей**, выполняющих длинные транзакции. Для OLTP — настройте таймауты и следите за пулом.
3. **Всегда ставьте `mysql-max_transaction_idle_time` в десятки секунд** (30–60 сек) вместо дефолтных 4 часов.
4. **Для read/write split внутри транзакций** — направляйте транзакционного пользователя на writer с `transaction_persistent = 1`, а не пытайтесь маршрутизировать `SELECT` на реплики.
5. **Мониторьте `extended_info` в `stats_mysql_processlist`** — это единственный способ понять, почему мультиплексинг не работает.
6. **Не используйте устаревшие переменные** (`mysql-forward_autocommit`, `mysql-default_tx_isolation`, `mysql-default_sql_mode` и др.) — они игнорируются или работают некорректно.
7. **При использовании prepared statements** — учитывайте, что они отключают мультиплексинг на время жизни statement'а. Планируйте размер пула соответственно.

## Дополнительная информация

### См. также
- **[ProxySQL: Обзор](./proxysql_overview.md)** — архитектура и базовая настройка.
- **[ProxySQL: Connection Pool и Multiplexing](./proxysql_connection_pool.md)** — как транзакции влияют на пул.
- **[ProxySQL: Query Rules и Query Cache](./proxysql_query_rules.md)** — маршрутизация и prepared statements.
- **[ProxySQL: Failover и мониторинг репликации](./proxysql_failover.md)** — поведение транзакций при отказах.
- **[ProxySQL: Конфигурация и переменные](./proxysql_configuration.md)** — слои конфигурации, LOAD/SAVE, переменные.

### Официальная документация
- [Multiplexing](https://proxysql.com/documentation/multiplexing/)
- [MySQL Variables](https://proxysql.com/documentation/global-variables/mysql-variables/)
- [FAQ](https://proxysql.com/documentation/faq/)