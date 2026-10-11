# Управление соединениями MySQL: max_connections, перегрузка, защита от подбора паролей

**Актуально для:** MySQL 8.0.x / 8.4 LTS / 9.x Innovation

`ERROR 1040 (HY000): Too many connections` — самая частая причина недоступности MySQL,
причём она не требует ни сбоя, ни перезагрузки: сервер штатно отказывает в новых
соединениях. Этот файл закрывает эксплуатационную сторону управления соединениями:
как их посчитать, как найти источник утечки, как пережить всплеск и как защитить сервер
от перебора паролей.

Партнёры по теме: [Конфигурация MySQL](./configuration.md) — `max_connections`,
`wait_timeout`, расчёт памяти; [Мониторинг MySQL](./monitoring.md) — метрики соединений;
[ProxySQL: пул соединений](./ProxySQL/proxysql_connection_pool.md) — мультиплексинг на
уровне прокси.

## Определения

| Термин | Значение |
| :--- | :--- |
| `max_connections` | Максимум одновременных клиентских соединений |
| Connection slot | Слот соединения в смысле сервера: память под буферы выделяется на всё время соединения |
| `wait_timeout` | Время простоя неинтерактивного соединения до автоматического закрытия |
| `interactive_timeout` | То же для интерактивного соединения (`mysql` с терминала) |
| `back_log` | Размер очереди входящих соединений, ожидающих обработки |
| `thread_cache_size` | Число потоков, сохраняемых для повторного использования после закрытия соединения |
| `CONNECTION_ADMIN` | Привилегия, дающая право видеть и прерывать чужие соединения |
| `SERVICE_CONNECTION_ADMIN` | Привилегия, необходимая для подключения через административный интерфейс |
| Administrative interface | Отдельный TCP-порт исключительно для административных подключений |

## Базовые концепции

### Три порта, о которых забывают при настройке firewall

| Порт | Протокол | Назначение |
| :--- | :--- | :--- |
| `3306` | Classic MySQL protocol | Основной порт для клиентов, утилит `mysqldump`, `mysqlpump`, коннекторов |
| `33060` | X Protocol (`mysqlx_port`) | MySQL Shell, MySQL Router, X DevAPI. **В MySQL 8.0 X Plugin включён по умолчанию** |
| `33062` | Administrative interface (`admin_port`) | Административные подключения, доступны с MySQL 8.0.14 |

Порт X Protocol вычисляется как `port × 10`: при `port = 3306` получается `33060`.
Порт MySQL Shell для проверки инстансов в составе InnoDB Cluster — `33061`.

Практический вывод: **правило firewall `3306/tcp` не означает, что MySQL слушает только
один порт**. На MySQL 8.0 по умолчанию открыты ещё `33060` и, при заданном
`admin_address`, `33062`. Проверить фактическое состояние:

```sql
SHOW VARIABLES WHERE Variable_name IN
  ('port', 'mysqlx_port', 'mysqlx', 'admin_port', 'admin_address', 'bind_address');
-- → Variable_name | admin_address | admin_port | bind_address | mysqlx | mysqlx_port | port
-- →               |               |     33062 | 0.0.0.0      | ON     |       33060 | 3306
```

Если X Protocol не используется, его следует закрыть: это отдельная поверхность атаки
с собственным TLS-контекстом.

```ini
[mysqld]
mysqlx = OFF
mysqlx_port = 33060
```

### Административный интерфейс

По умолчанию сервер допускает **одно** административное соединение — дополнительное
к `max_connections`, зарезервированное за учётными записями с привилегией
`CONNECTION_ADMIN` (или устаревшей `SUPER`).

Административный интерфейс снимает это ограничение:

| Свойство | Значение |
| :--- | :--- |
| Появление | MySQL 8.0.14 |
| Условие включения | `admin_address` задан при старте; иначе интерфейс не создаётся |
| Порт | `admin_port`, по умолчанию `33062` |
| Ограничение числа соединений | Отсутствует |
| Требуемая привилегия | `SERVICE_CONNECTION_ADMIN` |
| Шифрование | Поддерживается, собственным TLS-контекстом (`admin_ssl_*`) |

```ini
[mysqld]
admin_address = 127.0.0.1
admin_port    = 33064
```

```bash
mysql --protocol=TCP --port=33064 --ssl-ca=admin-ca.pem --ssl-cert=client-cert.pem --ssl-key=client-key.pem
# → подключение к административному интерфейсу
```

> **Осторожность:** интерфейс на `127.0.0.1` безопасен для локальных автоматизаций.
> Вынос на сетевой адрес открывает неограниченное по числу соединений окно,
> защищённое только привилегией `SERVICE_CONNECTION_ADMIN` и TLS.

### Расчёт памяти под соединения

Каждое соединение резервирует память под буферы **на всё время существования**, даже
если не выполняет запроса:

```
innodb_buffer_pool_size
  + (sort_buffer_size + join_buffer_size + read_buffer_size
     + read_rnd_buffer_size + net_buffer_length + thread_stack) × max_connections
  + служебные 1–2 ГБ
≤ физическая память
```

Отсюда правило: **`max_connections` — это не «сколько соединений нам нужно», а верхняя
граница памяти, которую вы согласны зарезервировать**. Увеличение его вдвое удваивает
не только количество слотов, но и потенциальную нагрузку на память под каждой сессией.

Альтернатива — ограничить память на уровне учётной записи (доступно с MySQL 8.0.28):

| Переменная | Назначение |
| :--- | :--- |
| `connection_memory_limit` | Максимум памяти для одного пользовательского соединения; при превышении его запросы отклоняются |
| `global_connection_memory_limit` | Максимум памяти для всех пользовательских соединений; при превышении запросы обычных пользователей отклоняются |

Обе не применяются к системным учётным записям вроде `root`.

### Модель потоков и thread pool

Стандартная модель MySQL — один поток на соединение. При тысяче соединений это тысяча
потоков, даже если 990 из них простаивают.

| Вариант | Доступность |
| :--- | :--- |
| `thread_pool` плагин в MySQL | MySQL Enterprise Edition (несколько возможностей ранее были только в MySQL Database Service) |
| `thread_pool` плагин в MariaDB | Штатная функциональность, `thread_handling = pool-of-threads` |
| Мультиплексинг на прокси | [ProxySQL](./ProxySQL/proxysql_connection_pool.md) — один клиентский поток обслуживает много серверных соединений |

Дополнительная переменная thread pool, добавленная в MySQL 8.0.31:
`thread_pool_max_transactions_limit` (ограничение числа активных транзакций).
В Percona Server для MySQL есть также `thread_pool_query_threads_per_group`
(по умолчанию один поток выполнения запросов на группу).

**Тюнинг thread pool (MySQL Enterprise / Percona Server).** Ключевые
переменные и их смысл:

| Переменная | Дефолт | Назначение |
| :--- | :--- | :--- |
| `thread_pool_size` | 16 | Число групп потоков; обычно = числу ядер CPU |
| `thread_pool_stall_limit` | 60 (мс) | Порог «застоя»: запрос дольше этого передаётся другому потоку, чтобы не блокировать группу |
| `thread_pool_oversubscribe` | 3 | Макс. дополнительных потоков на группу при пике |
| `thread_pool_max_threads` | 100000 | Абсолютный максимум потоков |
| `thread_pool_high_prio_tickets` | 4294967295 | «Билеты» высокого приоритета для транзакций |
| `thread_pool_max_transactions_limit` | 0 (off) | Ограничение числа активных транзакций (8.0.31+) |

Рекомендация Percona: thread pool даёт выигрыш при большом числе
соединений (порядка > 20 000). При сотнях соединений выгода минимальна,
а слишком малый `thread_pool_stall_limit` увеличивает контекстные
переключения. `thread_pool_size` больше числа ядер почти всегда вредит.

Практический вывод: если инсталляция Community Edition и соединений много, реальные
варианты — ограничить приложение пулом соединений на его стороне либо поставить
мультиплексирующий прокси. Увеличение `max_connections` проблему не решает, а усугубляет.

### Дефолты, системные ограничения и настройки ОС

**Дефолты переменных соединений** — важно понимать baseline, чтобы отличить
настроенную политику от значений «из коробки»:

| Переменная | Дефолт | Комментарий |
| :--- | :--- | :--- |
| `max_connections` | `151` | Значение заложено в исходниках (`MAX_CONNECTIONS_DEFAULT` в `sql/sys_vars.h`); больше, чем дефолт Apache, чтобы избежать `Too many connections` в типовой настройке |
| `back_log` | `-1` (автосизинг) | С 8.0 автосизинг задаёт `back_log = max_connections`. В 5.7 формула была `50 + max_connections/5` (итого дефолт 80) |
| `thread_cache_size` | автосизинг | Рассчитывается как `8 + max_connections / 100`; `0` отключает кэш (новый поток на каждое соединение) |
| `wait_timeout` / `interactive_timeout` | `28800` с (8 ч) | Снижение до 300–600 с — стандартный SRE-паттерн |
| `max_allowed_packet` | 64 МБ | Изменено с 4 МБ в 8.0 |
| `connection_memory_limit` | `0` (отключено) | Доступно с 8.0.28; лимит памяти на одно соединение |
| `global_connection_memory_limit` | `0` (отключено) | Доступно с 8.0.28; лимит памяти на все соединения вместе |

**Системные ограничения ОС.** `back_log` — размер очереди `listen()` на уровне
приложения, но у ядра свой потолок. Проверяйте и настраивайте вместе:

```bash
# Ядро: listen-очередь и SYN-пакеты
sysctl -w net.core.somaxconn=10000
sysctl -w net.ipv4.tcp_max_syn_backlog=10000
sysctl -w net.core.netdev_max_backlog=10000

# Файловые дескрипторы: на соединение уходит ~2 FD (данные + индексы) плюс буферы
ulimit -n
# → 65535 (ожидаемо для настроенного инстанса)
```

`back_log` не может превышать `somaxconn` — если значение в `my.cnf` больше,
MySQL проигнорирует его без ошибки. При `max_connections > 10000` рекомендуется
поднять оба параметра до того же значения.

**Индикация кэша потоков.** Сравните счётчики, чтобы понять, нужен ли ручной
`thread_cache_size`:

```sql
SHOW STATUS LIKE 'Threads_created';
SHOW STATUS LIKE 'Connections';
SHOW STATUS LIKE 'Threads_cached';
-- → Threads_created / Connections > 0.01 — увеличьте thread_cache_size
```

### Сетевой стек ОС и соединения: что смотреть sysadmin

Поведение MySQL на соединениях определяется не только его переменными, но и
параметрами ядра и ulimit. Вот что проверять при утечках и ловушках.

**Соединения в состоянии TIME_WAIT.** Каждое закрытие TCP-соединения оставляет
сокет в `TIME_WAIT` на 60 с (дефолт). При высокой частоте подключений (например,
приложение открывает и закрывает соединение на каждый запрос) счётчик растёт:

```bash
# Сколько TIME_WAIT на хосте
ss -tan state time-wait | wc -l
# → 4821

# Кто именно — по удалённому адресу
ss -tan state time-wait | awk '{print $5}' | cut -d: -f1 | sort | uniq -c | sort -rn | head
# →  3210 10.0.4.15
# →  1284 10.0.4.16
```

Массовое `TIME_WAIT` от одного клиента — признак того, что приложение инициирует
закрытие (не держит соединение открытым). Решение — пул соединений на стороне
приложения, а не тюнинг ядра. Если без пула никак, то:

```bash
# Сократить TIME_WAIT (только если приложение не может использовать пул)
sysctl -w net.ipv4.tcp_fin_timeout = 30
sysctl -w net.ipv4.tcp_max_tw_buckets = 262144
```

**`net.ipv4.ip_local_port_range`.** Динамический диапазон портов для исходящих
соединений. При исчерпании диапазона новые исходящие соединения не установятся:

```bash
sysctl net.ipv4.ip_local_port_range
# → 32768 60999   # ~28K одновременных исходящих соединений

# При нехватке — расширить:
sysctl -w net.ipv4.ip_local_port_range="1024 65535"
```

**`net.core.somaxconn` и `net.ipv4.tcp_max_syn_backlog`.** Потолки для `back_log`
и очереди SYN. MySQL не поднимет `back_log` выше, что установлено в ядре:

```bash
sysctl net.core.somaxconn
# → 4096   # если back_log в my.cnf = 512 — ок; если 10000 — ограничится 4096
```

**ulimit на файловые дескрипторы.** На одно соединение приходится ~2 дескриптора
(данные + индексы), плюс буферы, плюс системные. При `max_connections = 10000`
требуется минимум ~20 000 FD, и это без учёта бэкапов, репликации, мониторинга:

```bash
# Текущий лимит
ulimit -n
# → 1024   # критически мало

# Для systemd-сервиса:
cat <<EOF | sudo tee /etc/systemd/system/mysql.conf.d/limits.conf
[Service]
LimitNOFILE = 65535
EOF
sudo systemctl daemon-reload
```

**Проверка фактического использования.** На живом сервере:

```bash
# Сколько дескрипторов держит mysqld
ls -la /proc/$(pidof mysqld)/fd | wc -l
# → 18432   # резкий рост может указывать на утечку

# Сколько соединений в TIME_WAIT на стороне сервера
ss -tan state time-wait | wc -l
```

### Проверка из ОС перед перезапуском приложения

Когда приложение «падает» и оставляет соединения в `Sleep`, перед перезапуском
убедитесь, что старые соединения не блокируют новые:

```bash
# Кто держит соединения с порта приложения
ss -tnp | grep -E 'ESTAB' | grep app_process
# → LISTEN 0 512 0.0.0.0:8080 0.0.0.0:* users:(("app",pid=1234))

# Количество established-соединений к MySQL
ss -tnp | grep ':3306' | grep -c ESTAB
# → 1001
```

## Практические сценарии

### Сценарий 1. Диагностика «Too many connections»

```sql
-- Что сейчас происходит
SHOW STATUS WHERE Variable_name IN
  ('Threads_connected', 'Threads_running', 'Max_used_connections', 'Connections',
   'Aborted_connects', 'Connection_errors_max_connections',
   'Connection_errors_internal', 'Connection_errors_peer_address');
-- → Variable_name                   | Value
-- → Threads_connected               | 1001
-- → Threads_running                 |    3
-- → Max_used_connections            |  987
-- → Connections                     | 48291023
-- → Aborted_connects                |   12043
-- → Connection_errors_max_connections|  18420   ← вот причина ошибок у клиентов
```

Три счётчика отвечают на разные вопросы:

| Счётчик | Вопрос |
| :--- | :--- |
| `Connection_errors_max_connections` | Сколько попыток подключения отклонено из-за исчерпания `max_connections` |
| `Connection_errors_peer_address` | Сколько отклонено из-за отсутствия файла, сокета или сетевого пути до клиента |
| `Connection_errors_internal` | Сколько отклонено по внутренним причинам |
| `Aborted_connects` | Сколько соединений прервано |
| `Max_used_connections` | Исторический максимум — сравните с `max_connections`, чтобы понять запас |

Кто именно подключён:

```sql
SELECT user, host, db, command, time, state,
       LEFT(INFO, 100) AS query_head
FROM information_schema.PROCESSLIST
ORDER BY time DESC
LIMIT 20;
-- → user  | host          | db   | command | time | state
-- → app   | 10.0.4.15:51234| shop | Sleep   |  821 | (NULL)
-- → app   | 10.0.4.15:51235| shop | Query   |    0 | executing
-- → backup| 10.0.9.2:44210 | NULL | Query   |    3 | waiting for table flush
```

Группировка по владельцу соединений:

```sql
SELECT user, SUBSTRING_INDEX(host, ':', 1) AS client_ip,
       COUNT(*) AS connections,
       SUM(command = 'Sleep') AS sleeping,
       SUM(command = 'Query')  AS running
FROM information_schema.PROCESSLIST
GROUP BY user, client_ip
ORDER BY connections DESC
LIMIT 15;
-- → user   | client_ip | connections | sleeping | running
-- → app    | 10.0.4.15 |         480 |       478 |       2
-- → report | 10.0.9.7  |          52 |        52 |       0
-- → backup | 10.0.9.2  |           1 |         0 |       1
```

### Сценарий 2. Экстренное освобождение слотов

Когда `max_connections` исчерпан, подключиться обычным способом уже нельзя.
Резервное административное соединение — единственный путь.

```bash
# Зайти по сокету root (не занимает сетевой слот)
mysql -S /var/run/mysqld/mysqld.sock -u root -p
```

```sql
-- Убить все простаивающие соединения приложения (осторожно: оборвёт транзакции в Query)
KILL CONNECTION 4821;
-- → Query OK, 0 rows affected

-- Убить все Idle-соединения старше 60 секунд
SELECT GROUP_CONCAT(id ORDER BY id) INTO @ids
FROM information_schema.PROCESSLIST
WHERE command = 'Sleep' AND time > 60 AND user LIKE 'app@%';
-- → @ids = "4821,4822,4823"

-- PREPARE выполняет только ОДИН оператор, поэтому много KILL через него не собрать.
-- Практичный путь — сгенерировать скрипт и выполнить его файлом:
mysql -N -B -e "SELECT CONCAT('KILL CONNECTION ', id) \
  FROM information_schema.PROCESSLIST \
  WHERE command='Sleep' AND time>60" > /tmp/kill.sql
mysql < /tmp/kill.sql
# → KILL CONNECTION 4821
# → KILL CONNECTION 4822

-- Для единичных случаев — вручную на каждый идентификатор:
KILL CONNECTION 4821;
-- → Query OK, 0 rows affected

-- Временно поднять лимит (теряется при рестарте без SET PERSIST)
SET GLOBAL max_connections = 1500;
-- → Query OK, 0 rows affected
```

Прервать только конкретный запрос, оставив соединение:

```sql
SELECT id, user, time, LEFT(info, 80) AS q FROM information_schema.PROCESSLIST
WHERE command = 'Query' AND time > 300 AND db NOT IN ('mysql','performance_schema','sys');
-- → id   | user | time | q
-- → 9012 | app  |  612 | SELECT * FROM events WHERE created_at > ...

KILL QUERY 9012;
-- → Query OK, 0 rows affected (соединение остаётся, запрос прерван)
```

Разница между `KILL CONNECTION` и `KILL QUERY` критична: `KILL CONNECTION` закрывает
соединение и **откатывает его незавершённую транзакцию**.

> **Осторожность:** массовый `KILL CONNECTION` по фильтру `Sleep` безопасен только если
> вы уверены, что в этих соединениях нет транзакций. Соединение в состоянии `Sleep`
> может принадлежать транзакции, оставившей изменённые строки незафиксированными.

### Сценарий 3. Настройка таймаутов и пула потоков

```ini
[mysqld]
max_connections      = 1000
back_log             = 512

# Не держать соединения по 8 часов: быстрый возврат слота после сбоя приложения
wait_timeout         = 600
interactive_timeout  = 600

# Переиспользовать потоки вместо создания новых
thread_cache_size    = 100
```

Значения по умолчанию для `wait_timeout` и `interactive_timeout` — 28800 секунд
(8 часов). Это значит, что после падения приложения его соединения держат слоты
до восьми часов.

Проверка:

```sql
SHOW VARIABLES WHERE Variable_name IN
  ('max_connections','back_log','wait_timeout','interactive_timeout','thread_cache_size');
-- → Variable_name      | Value
-- → back_log           | 512
-- → interactive_timeout| 600
-- → max_connections    | 1000
-- → thread_cache_size  | 100
-- → wait_timeout       | 600
```

> **Замечание:** уменьшение `wait_timeout` вынуждает клиентов с JDBC/соединениями без
> проверки простоя переподключаться. Проверьте, что драйвер и пул на стороне приложения
> умеют обрабатывать разрыв и пересоздавать соединение.

### Сценарий 4. Защита от перебора паролей (Connection Control)

**Два механизма — плагины и компонент.** Изначально защита реализована как два
плагина (`CONNECTION_CONTROL` и `CONNECTION_CONTROL_FAILED_LOGIN_ATTEMPTS`,
оба в библиотеке `connection_control.so`). В MySQL 9.2 появился компонент
`component_connection_control`, который их заменяет; плагины в 9.x помечены как
устаревающие и подлежат удалению в будущей версии. В 8.4 оба подхода работают.

**Плагины (8.0–8.4, legacy):**

```sql
INSTALL PLUGIN connection_control SONAME 'connection_control.so';
-- → Query OK, 0 rows affected
```

**Компонент (9.2+, рекомендуемый путь):**

```sql
INSTALL COMPONENT 'file://component_connection_control';
-- → Query OK, 0 rows affected
```

При миграции с плагинов на компонент переменные переименовываются:

| Плагин | Компонент |
| :--- | :--- |
| `connection_control_failed_connections_threshold` | `component_connection_control.failed_connections_threshold` |
| `connection_control_min_connection_delay` | `component_connection_control.min_connection_delay` |
| `connection_control_max_connection_delay` | `component_connection_control.max_connection_delay` |

Миграция по шагам: удалить ссылки на плагины из конфига, uninstall оба плагина,
установить компонент, перенести значения переменных через `SET PERSIST`,
перезапустить сервер.

**Настройка (общая для обоих подходов, имена переменных приведены для плагина):**

| Переменная | По умолчанию | Диапазон | Назначение |
| :--- | :--- | :--- | :--- |
| `connection_control_failed_connections_threshold` | `3` | 0–2147483647 | Разрешённое число последовательных неудач до включения задержки |
| `connection_control_min_connection_delay` | `1000` мс | 1000–2147483647 | Начальная задержка ответа |
| `connection_control_max_connection_delay` | `2147483647` мс | 1000–2147483647 | Потолок задержки |

Механика: при значении `N > 0` задержка включается начиная с неудачной попытки `N + 1`.
Если для учётной записи задержка уже включена, она применяется и к следующей
**успешной** попытке. Установка `threshold = 0` полностью отключает подсчёт неудач.

```sql
SET GLOBAL connection_control_failed_connections_threshold = 5;
SET GLOBAL connection_control_min_connection_delay         = 2000;
SET GLOBAL connection_control_max_connection_delay         = 3600000;
-- → Query OK, 0 rows affected
```

**Мониторинг.** Счётчик задержек:

```sql
SHOW STATUS LIKE 'Connection_control_delay_generated';
-- → Variable_name                      | Value
-- → Connection_control_delay_generated |      184
```

Счётчик обнуляется при каждом изменении `connection_control_failed_connections_threshold`
на рантайме — это важно при интерпретации показаний: нелинейный рост счётчика между
двумя чтениями надёжнее абсолютного значения.

**Детализация по учётным записям.** Таблица `CONNECTION_CONTROL_FAILED_LOGIN_ATTEMPTS`
предоставляется **отдельным плагином** с тем же именем, поэтому может отсутствовать при
установленном `CONNECTION_CONTROL`. В 9.x детализация перешла в Performance Schema
таблицу `connection_control_failed_login_attempts`.

```sql
INSTALL PLUGIN CONNECTION_CONTROL_FAILED_LOGIN_ATTEMPTS
  SONAME 'connection_control.so';
-- → Query OK, 0 rows affected

SELECT USER, HOST, FAILURE_COUNT, MINIMUM_FAILURES
FROM INFORMATION_SCHEMA.CONNECTION_CONTROL_FAILED_LOGIN_ATTEMPTS
ORDER BY FAILURE_COUNT DESC
LIMIT 10;
-- → USER       | HOST       | FAILURE_COUNT | MINIMUM_FAILURES
-- → app_backup | 10.0.9.200 |            412 |               5
```

`FAILURE_COUNT` считает все неудачные попытки, независимо от того, была ли на них
задержка; `MINIMUM_FAILURES` — порог, при котором задержка включается.

> **Версии:** в MySQL 8.4 эти три переменные — штатные и не объявлены устаревшими.
> В руководстве ветки Innovation (9.7) они помечены как `Deprecated`. Если в вашей
> инсталляции переход на Innovation планируется, сверьтесь с руководством целевой версии
> перед переносом конфигурации.

### Сценарий 5. Ограничение числа соединений пользователя

```sql
-- Не более 20 соединений от учётной записи
CREATE USER 'report'@'10.%' IDENTIFIED BY '...'
  WITH MAX_USER_CONNECTIONS 20;
-- → Query OK, 0 rows affected

ALTER USER 'report'@'10.%' WITH MAX_USER_CONNECTIONS 10;
-- → Query OK, 0 rows affected

SHOW CREATE USER 'report'@'10.%';
```

Проверка фактического числа соединений и наличия ограничений:

```sql
-- Лимиты хранятся в mysql.user; имена колонок в таблице отличаются
-- от имён ресурсов в CREATE USER ... WITH
SELECT user, host,
       max_user_connections AS max_concurrent,   -- MAX_USER_CONNECTIONS
       max_questions        AS max_q_per_hour,   -- MAX_QUERIES_PER_HOUR
       max_updates          AS max_upd_per_hour, -- MAX_UPDATES_PER_HOUR
       max_connections      AS max_conn_per_hour -- MAX_CONNECTIONS_PER_HOUR
FROM mysql.user
WHERE user NOT IN ('mysql.sys','mysql.session','mysql.infoschema')
  AND (max_user_connections > 0 OR max_questions > 0
       OR max_updates > 0 OR max_connections > 0);
-- → user   | host   | max_concurrent | max_q_per_hour | max_upd_per_hour | max_conn_per_hour
-- → report | 10.%   |             20 |             100|               50 |                  5
```

Как считаются и сбрасываются лимиты:

- Лимит на одновременные соединения = `MAX_USER_CONNECTIONS`, если он ненулевой;
  иначе применяется глобальная `max_user_connections`; если и она 0 — ограничения нет.
- Учёт идёт **на учётную запись** (строку `mysql.user`), а не на соединение: два
  одновременных клиента одной учётной записи делят общий счётчик.
- Сброс почасовых счётчиков: `FLUSH USER_RESOURCES` для всех учётных записей либо
  повторное присвоение лимита тому же значению для конкретной учётной записи.
  Также сбрасывает `FLUSH PRIVILEGES`. `FLUSH USER_RESOURCES` не затрагивает
  `MAX_USER_CONNECTIONS`.
- Счётчики обнуляются при старте сервера и не переживают перезапуск.
- Ошибки: `ER_TOO_MANY_USER_CONNECTIONS` и `ER_USER_LIMIT_REACHED`. Первая также может
  возникнуть при быстром `disconnect` + `connect`, если сервер ещё не обработал отключение;
  после обработки отключения соединение снова разрешено.

### Сценарий 6. Мониторинг соединений

```sql
-- Однократный срез
SELECT user, COUNT(*) AS connections
FROM information_schema.PROCESSLIST GROUP BY user ORDER BY connections DESC;

-- Текущий processlist с форматированием через sys schema
SELECT * FROM sys.processlist LIMIT 20;

-- Инцидент: кто и откуда подключается
SELECT IP, HOST, HOST_VALIDATED, SUM_CONNECT_ERRORS, COUNT_HANDSHAKE_ERRORS,
       FIRST_SEEN, LAST_SEEN
FROM performance_schema.host_cache
WHERE SUM_CONNECT_ERRORS > 0
ORDER BY SUM_CONNECT_ERRORS DESC
LIMIT 10;
```

Метрики для экспорта в Prometheus/Zabbix — см. [Мониторинг MySQL](./monitoring.md).
Ключевой набор: `Threads_connected`, `Threads_running`, `Max_used_connections`,
`Aborted_connects`, `Connection_errors_max_connections`, `Aborted_clients`.

Алерт на исчерпание соединений накапливается, а не срабатывает мгновенно:

```
rate(Connection_errors_max_connections[5m]) > 0
```

Разовое превышение `Threads_connected` детектора деградации — ложное срабатывание;
рост счётчика отклонённых подключений означает реальную недоступность для клиентов.

### Сценарий 7. Диагностика медленного закрытия соединений

Если соединения накапливаются и не закрываются, проблема в приложении или сети,
а не в MySQL:

```sql
-- Со стороны сервера: сколько соединений длится дольше ожидаемого
SELECT user, COUNT(*) AS stale
FROM information_schema.PROCESSLIST
WHERE command = 'Sleep' AND time > 3600
GROUP BY user;
-- → user | stale
-- → app  |  312
```

Массовый `Sleep` дольше часа — признак либо утечки соединений в приложении, либо
неработающего механизма проверки простоя на стороне пула. Диагностика TCP-слоя
(TIME_WAIT, `ip_local_port_range`, `somaxconn`) — в разделе
**Сетевой стек ОС и соединения** выше. Подробнее —
[Connection Pooling](../../Networking/Concepts/connection_pooling.md).

### Сценарий 8. Проверка достижимости с учётом всех портов

```bash
# Основной порт
mysqladmin --protocol=TCP -h 127.0.0.1 -P 3306 -u monitoring -p ping
# → mysqld is alive

# X Protocol
mysqlsh --mysqlx -h 127.0.0.1 --port 33060 -u monitoring -p --sql -e "SELECT 1"
# → +---+
# → | 1 |
# → +---+

# Что реально слушает процесс
ss -ltnp | grep mysqld
# → LISTEN 0 151 0.0.0.0:3306    0.0.0.0:*  users:(("mysqld",pid=1234,fd=30))
# → LISTEN 0 151 0.0.0.0:33060  0.0.0.0:*  users:(("mysqld",pid=1234,fd=31))
# → LISTEN 0 151 0.0.0.0:33062  0.0.0.0:*  users:(("mysqld",pid=1234,fd=32))
```

Несоответствие между `SHOW VARIABLES` и `ss -ltnp` означает либо незакоммиченную
конфигурацию, либо активное перекрытие портов другим процессом.

## Устранение неисправностей (Troubleshooting)

| Проблема | Вероятная причина | Решение |
| :--- | :--- | :--- |
| `ERROR 1040: Too many connections` | Исчерпан `max_connections` | Подключиться по сокету как `root`; убить `Sleep`; временно поднять `max_connections`; найти источник |
| `ERROR 1040` сразу после рестарта | Приложения подключаются быстрее, чем сервер обрабатывает | Увеличить `back_log`; настроить пул на стороне приложения |
| `Access denied for user` при верном пароле | Задержка от `connection_control` на успешной попытке после серии неудач | Проверить `connection_control_failed_connections_threshold`; временно установить `0` для диагностики |
| Рост памяти без роста `Threads_connected` | Высокая `tmp_table_size` / `sort_buffer_size` при небольшом числе соединений | Проверить индивидуальный расход: `sys.memory_by_thread_by_current_bytes` |
| OOM при большом числе соединений | `max_connections` выставлен без учёта буферов | Пересчитать память по формуле; снизить лимит либо размеры буферов |
| `Aborted_connects` растёт при низкой нагрузке | Переподключения приложения | Проверить `wait_timeout` и настройки клиентского пула |
| Соединения накапливаются после деплоя | Новая версия приложения не закрывает соединения | Найти владельца через `PROCESSLIST`, сравнить с ожидаемым |
| Порт 33060 открыт, но не используется | X Plugin включён по умолчанию в 8.0 | Закрыть в firewall либо выключить `mysqlx = OFF` |
| `Connection_errors_peer_address` растёт | Проблема с сокетом или сетевым маршрутом до клиента | Проверить права на unix-сокет, маршрутизацию, DNS |
| `TIME_WAIT` растёт на стороне клиента | Приложение инициирует закрытие на каждый запрос | Использовать пул соединений; при необходимости — `tcp_fin_timeout` |
| `Can't connect` — `Connection refused` | Порт закрыт или `bind_address` не совпадает | `ss -ltnp`, firewall, `bind_address` |
| `Too many connections` на бэкенде через прокси | Сумма `max_connections` всех прокси-узлов превышает лимит бэкенда | Согласовать `mysql_servers.max_connections` с `max_connections` бэкенда |
| `Aborted connection` в логах после правки пула | `mysql-connection_max_age_ms` закрывает соединения без `COM_QUIT` | Штатное поведение; снизить `connection_max_age_ms` или проигнорировать |

## Лучшие практики

- **`max_connections` — производная величина от памяти**, а не от желаемой нагрузки.
  Считать от `innodb_buffer_pool_size` и размеров буферов.
- **Уменьшить `wait_timeout`.** Значение по умолчанию в 8 часов превращает упавшее
  приложение в восьмичасовую утечку слотов.
- **Иметь рабочий путь в обход сети.** Unix-сокет с доступом `root` — единственная
  возможность диагностики при исчерпанном `max_connections`. Проверьте его работоспособность
  заранее, а не во время инцидента.
- **Считать отказы, а не только загрузку.** `Connection_errors_max_connections`
  показывает реальную боль клиентов; `Threads_connected` показывает только состояние.
- **Закрывать X Protocol, если он не используется.** Лишний открытый порт — лишняя
  поверхность.
- **Ограничивать перебор паролей плагином `CONNECTION_CONTROL`** (или компонентом
  `component_connection_control` в 9.x) и мониторить `CONNECTION_CONTROL_FAILED_LOGIN_ATTEMPTS`:
  всплеск неудачных попыток по одной учётной записи — признак атаки.
- **Не убивать соединения массово без проверки транзакций.** `KILL CONNECTION`
  откатывает незавершённую транзакцию.
- **Согласовывать `max_connections` бэкенда с прокси.** Сумма лимитов всех прокси-узлов
  плюс запас на прямые подключения (мониторинг, репликация, админы) должна быть ниже
  `max_connections` бэкенда.
- **Проверять ядро вместе с `back_log`.** `somaxconn` и `tcp_max_syn_backlog` — потолки
  для очереди соединений; `back_log` выше них MySQL проигнорирует без ошибки.
- **Следить за `ip_local_port_range` и `TIME_WAIT` на стороне клиента.** При исчерпании
  диапазона портов новые соединения не установятся.

## Дополнительная информа

### Граничные случаи и ограничения

- **`mysqld` фактически допускает `max_connections + 1` клиентских соединений.**
  Дополнительное зарезервировано для учётных записей с привилегией `CONNECTION_ADMIN`
  (или устаревшей `SUPER`).
- **Административный интерфейс включается только при заданном `admin_address`.**
  Без него переменная `admin_port` присутствует в списке, но интерфейс не создаётся —
  легко принять за неработающую настройку.
- **Число административных соединений на отдельном интерфейсе не ограничено**, но
  допускаются только для учётных записей с `SERVICE_CONNECTION_ADMIN`. Локальный
  административный слот на обычном интерфейсе — ровно один.
- **Внутренние сессии Group Replication с MySQL 8.0.19 не учитываются в
  `max_connections`.** В релизах до 8.0.19 учитывались, и запуск Group Replication при
  достигнутом лимите был невозможен — сервер или сам Group Replication мог
  остановиться.
- **`thread_cache_size` влияет только на скорость переиспользования потоков**, а не на
  лимит соединений.
- **`wait_timeout` не действует на соединения, удерживающие незавершённую транзакцию:**
  такие соединения остаются до завершения или отката.
- **`connection_memory_limit` (8.0.28+) ограничивает память на одно соединение** и
  `global_connection_memory_limit` — на все соединения вместе. Обе не применяются к
  системным учётным записям вроде `root`. Позволяют ограничить ущерб от одной
  «плохой» сессии без снижения `max_connections`. Подробнее — в
  [Конфигурации MySQL](./configuration.md).
- **`Created_tmp_disk_tables` считает только внутренние временные таблицы, созданные на
  диске**, и не отражает расход памяти на сортировки и соединения. Для оценки памяти
  на соединение использовать `sys.memory_by_thread_by_current_bytes`.

### Внешние ресурсы

- [MySQL Reference Manual: Connection Management](https://dev.mysql.com/doc/refman/8.0/en/connection-management.html)
- [MySQL Reference Manual: Too many connections](https://dev.mysql.com/doc/refman/8.0/en/too-many-connections.html)
- [MySQL Reference Manual: Administrative Connection Interface](https://dev.mysql.com/doc/refman/8.0/en/administrative-connection-interface.html)
- [MySQL Reference Manual: Connection Control Plugins](https://dev.mysql.com/doc/refman/8.4/en/connection-control-plugin.html)
- [MySQL Reference Manual: Connection Control Component (9.x)](https://dev.mysql.com/doc/refman/9.7/en/connection-control-component.html)
- [MySQL Port Reference: Client-Server Connection Ports](https://dev.mysql.com/doc/mysql-port-reference/en/mysql-port-reference-tables.html)
- [MySQL Connection Handling and Scaling (Oracle MySQL Blog)](https://dev.mysql.com/blog-archive/mysql-connection-handling-and-scaling/) — rationale для `max_connections`, thread cache и thread pool

### См. также

- **[Конфигурация MySQL (my.cnf)](./configuration.md)** — `max_connections`, `back_log`,
  `wait_timeout`, расчёт памяти, `SET PERSIST`.
- **[Мониторинг MySQL](./monitoring.md)** — метрики соединений и алерты.
- **[ProxySQL: пул соединений и мультиплексинг](./ProxySQL/proxysql_connection_pool.md)** —
  альтернатива увеличению `max_connections`.
- **[Connection Pooling](../../Networking/Concepts/connection_pooling.md)** — пулы на
  стороне клиента и приложения.
- **[Роли и управление привилегиями](./role_management.md)** — `CONNECTION_ADMIN`,
  `SERVICE_CONNECTION_ADMIN`, `MAX_USER_CONNECTIONS`.
- **[Performance Schema и sys schema](./Operations/performance-schema-and-sys.md)** —
  `processlist`, `host_cache`, распределение памяти по потокам.