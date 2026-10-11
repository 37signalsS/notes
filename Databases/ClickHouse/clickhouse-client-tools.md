# ClickHouse — Клиентский инструментарий

**Актуально для:** ClickHouse 26.9.12.8 (Stable) / 26.8.20.9 (LTS)

## Определения

**clickhouse-client** — консольный клиент для подключения к серверу ClickHouse по нативному TCP-протоколу (порт 9000). Основной инструмент администрирования.

**clickhouse-local** — утилита для выполнения SQL-запросов над локальными файлами (CSV, TSV, Parquet, JSON и др.) **без запуска сервера**. Поддерживает табличные функции (`file()`, `s3()`, `url()` и др.) и большинство SQL-возможностей, но не поддерживает распределённые таблицы, репликацию и Keeper. Запускается как отдельный бинарь `clickhouse-local` или как подкоманда `clickhouse local` (с 26.x предпочтительнее подкоманда).

**clickhouse-benchmark** — утилита нагрузочного тестирования одиночного запроса: многократное выполнение с замером percentiles времени выполнения.

**clickhouse-format** — форматирование SQL по стилевому гайду ClickHouse.

**clickhouse-extract-from-config** — извлечение значений из `config.xml` по пути (полезно для отладки конфигурации).

**clickhouse-keeper-client** — интерактивный клиент для ClickHouse Keeper / ZooKeeper (протокол совместим с ZooKeeper). По умолчанию подключается к порту **9181** (не 2181 — последний используется классическим ZooKeeper).

**clickhouse-odbc-bridge / clickhouse-library-bridge** — отдельные процессы-мосты, позволяющие использовать ODBC-источники и пользовательские библиотеки в качестве источников словарей.

**Native TCP vs HTTP** — два протокола доступа к серверу. Native (порт 9000, бинарный, меньше накладных расходов) используется `clickhouse-client` и драйверами. HTTP (порт 8123) — универсальный REST-интерфейс для любого языка.

## Предварительные требования

### Программное обеспечение
- **ClickHouse клиентские пакеты**: `clickhouse-client`, `clickhouse-common-static` (включает `clickhouse-local`, `clickhouse-benchmark`, `clickhouse-format`, `clickhouse-extract-from-config`, `clickhouse-keeper-client`, мосты)
- **Минимальная версия**: 23.8+ для большинства флагов, 24.3+ для `clickhouse-local` с табличными функциями S3/URL, 25.1+ для `clickhouse-format`
- **ОС**: Linux (x86_64, aarch64), macOS (x86_64, aarch64), FreeBSD
- **Сетевое окружение**: доступ к портам 9000 (Native TCP), 8123 (HTTP), 9440 (Native TLS), 8443 (HTTPS) — в зависимости от конфигурации сервера

### Начальное состояние окружения
- ClickHouse сервер запущен и доступен по сети
- Пользователь создан в `users.xml` или `users.d/` с необходимыми правами
- Для TLS-подключений: сертификаты CA/клиента настроены на сервере и клиенте
- Для `clickhouse-local`: файлы для анализа доступны локально или по S3/HTTP

### Проверка установки
```bash
# Версия клиента
clickhouse-client --version
# → ClickHouse client version 26.9.12.8 (official build)

# Проверка доступности утилит
clickhouse-local --version
clickhouse-benchmark --version
clickhouse-format --version
clickhouse-keeper-client --version

# Тест подключения к серверу
clickhouse-client --host localhost --port 9000 --query "SELECT 1"
# → 1
```

## Конфигурация клиента

`clickhouse-client` (и `clickhouse-benchmark`) читают конфигурацию из первого существующего файла в порядке приоритета:

1. `-c / --config-file / --config` — явный путь
2. `./clickhouse-client.[xml|yaml|yml]` — локальный в текущей директории
3. `$XDG_CONFIG_HOME/clickhouse/config.[xml|yaml|yml]` (или `~/.config/clickhouse/config.`, если `XDG_CONFIG_HOME` не задан)
4. `~/.clickhouse-client/config.[xml|yaml]` — устаревшее, но всё ещё читается
5. `/etc/clickhouse-client/config.[xml|yaml]` — системный

### Подключение по именам (connections_credentials)

Сохраняйте учётные данные в конфиге, а не в командной строке — пароли не попадут в `ps`:

```xml
<!-- ~/.clickhouse-client/config.xml -->
<config>
    <connections_credentials>
        <connection>
            <name>prod</name>
            <hostname>clickhouse-prod.internal</hostname>
            <port>9000</port>
            <user>admin</user>
            <password>secret</password>
            <!-- <accept-invalid-certificate>1</accept-invalid-certificate> -->
            <!-- <prompt>\e[31m[PROD]\e[0m {user}@{host}</prompt> -->
        </connection>
        <connection>
            <name>prod_tls</name>
            <hostname>clickhouse-prod.internal</hostname>
            <port>9440</port>
            <secure>1</secure>
            <user>admin</user>
            <password>secret</password>
        </connection>
    </connections_credentials>
</config>
```

```yaml
# ~/.clickhouse-client/config.yaml (современный формат)
connections_credentials:
  connection:
    - name: prod
      hostname: clickhouse-prod.internal
      port: 9000
      user: admin
      password: '***'
    - name: prod_tls
      hostname: clickhouse-prod.internal
      port: 9440
      secure: 1
      user: admin
      password: '***'
```

Подключение по имени:
```bash
clickhouse-client --connection prod --query "SELECT 1"
# → 1

# TLS-подключение
clickhouse-client --connection prod_tls --query "SELECT 1"
```

### Безопасность: пароли

| Способ | Безопасность | Замечание |
| :--- | :--- | :--- |
| `--password '***'` | Низкая | Пароль виден в `ps aux`, истории оболочки |
| `CLICKHOUSE_PASSWORD=***` | Средняя | Переменная окружения видна в `ps`/`/proc` других пользователей |
| `--password` без значения (интерактивно) | Высокая | Запрашивается у терминала, не попадает в `ps` |
| Конфигурация `connections_credentials` | Высокая | Файл с правами 600, пароль не в командной строке |
| `--prompt` | Высокая | Интерактивный ввод перед каждым запросом |

```bash
# Интерактивный ввод пароля (рекомендуется)
clickhouse-client --host prod --user admin --password --query "SELECT 1"

# Через env-переменную
CLICKHOUSE_PASSWORD='***' clickhouse-client --host prod --query "SELECT 1"

# Очистка пароля из командной строки (автоматически при запуске)
# clickhouse-client и clickhouse-benchmark вызывают clearPasswordFromCommandLine,
# но это не защищает от истории оболочки
```

## Основные концепции

### Архитектура клиент-сервер

```
clickhouse-client ──(Native TCP :9000)──┐
curl / HTTP-клиенты ──(HTTP :8123)──────┼── clickhouse-server
драйверы (JDBC/ODBC/Python) ────────────┘
```

- **Native TCP (9000):** бинарный протокол, минимальные накладные расходы, поддержка всех возможностей (включая `send_logs_level`, потоковую передачу). Предпочтительный для продакшена.
- **HTTP (8123):** текстовый/REST, работает из любого языка и через прокси. Поддерживает `query`, `query_id`, `database`, `user`, `password` как параметры URL или заголовки.

### Когда какой инструмент

| Задача | Инструмент |
| :--- | :--- |
| Администрирование, DDL, диагностика | `clickhouse-client` |
| Разовый анализ файла без сервера | `clickhouse-local` |
| Тестирование производительности запроса | `clickhouse-benchmark` |
| Форматирование SQL | `clickhouse-format` |
| Отладка конфигурации | `clickhouse-extract-from-config` |
| Инспекция znode Keeper | `clickhouse-keeper-client` |
| Словарь из ODBC-источника | `clickhouse-odbc-bridge` |

## Практические сценарии

### clickhouse-client: подключение и флаги

```bash
# Подключение (интерактивный режим)
clickhouse-client --host clickhouse-01.internal --port 9000 --user default --password '***'
# → ClickHouse client version 26.9.12.8 (official build).
# → Connecting to clickhouse-01.internal:9000 as user default.
# → Connected to ClickHouse server version 26.9.12.8.
# → :)

# Выполнение запроса (неинтерактивно)
clickhouse-client --query "SELECT version()"
# → 26.9.12.8

# С указанием базы и формата вывода
clickhouse-client --database devops --query "SELECT * FROM logs LIMIT 10" --format PrettyCompact
# → ┌─id─┬─timestamp───────────┬─message──────────┐
# │ 1  │ 2026-01-15 10:30:00 │ User logged in   │
# │ 2  │ 2026-01-15 10:30:05 │ Request processed│
# └────┴─────────────────────┴──────────────────┘

# Замер времени выполнения
clickhouse-client --time --query "SELECT count() FROM logs"
# → 1000000
# → 
# → real    0.042 sec
# → user    0.018 sec
# → sys     0.004 sec

# Отправка логов запроса на клиент (для отладки)
clickhouse-client --send_logs_level=debug --query "SELECT 1"
# → [DEBUG] ... (логи выполнения запроса на stderr)
# → 1

# Стек-трейс при ошибке
clickhouse-client --stacktrace --query "SELECT unknown_function()"
# → Code: 43. DB::Exception: Unknown function unknown_function
# → Stack trace:
# → ...

# Множественные запросы из файла
clickhouse-client --multiquery < queries.sql
# → Результаты каждого запроса последовательно

# Передача данных через stdin
cat data.csv | clickhouse-client --query "INSERT INTO logs FORMAT CSV"
# → Ok.
# → 1000 rows inserted.

# Интерактивный режим с подсказками
clickhouse-client --multiline
# → ClickHouse client version 26.9.12.8 (official build).
# → Connecting to localhost:9000 as user default.
# → Connected to ClickHouse server version 26.9.12.8.
# → :)
# → SELECT * FROM logs WHERE
#    -> id = 1
#    ->
# → ┌─id─┬─message──────────┐
# │ 1  │ User logged in   │
# └────┴──────────────────┘
```

**Полезные флаги:**

| Флаг | Назначение |
| :--- | :--- |
| `--host`, `--port`, `--user`, `--password` | Параметры подключения |
| `--database` | База данных по умолчанию |
| `--query` | Выполнить запрос и выйти |
| `--time` | Вывести время выполнения |
| `--format` | Формат вывода (`TabSeparated`, `JSON`, `PrettyCompact`, `CSV`) |
| `--send_logs_level` | Уровень логов, отправляемых клиенту (`error`, `warning`, `info`, `debug`, `trace`) |
| `--stacktrace` | Показывать стек-трейс при ошибке |
| `--multiquery` | Разрешить несколько запросов в одном `--query` |
| `--echo` | Вывести запрос перед результатом |
| `--multiline` | Многострочный ввод в интерактивном режиме |

### HTTP-интерфейс (curl)

```bash
# Простой запрос
curl "http://clickhouse-01:8123/?query=SELECT%20version()"
# → 26.9.12.8

# POST с телом запроса
curl -X POST "http://clickhouse-01:8123/?database=devops" --data-binary @query.sql
# → (результат запроса в формате TabSeparated по умолчанию)

# С аутентификацией
curl -u default:'***' "http://clickhouse-01:8123/?query=SELECT%201"
# → 1

# Проверка доступности (health check)
curl "http://clickhouse-01:8123/ping"
# → Ok.

# Вставка данных
curl -X POST "http://clickhouse-01:8123/?query=INSERT%20INTO%20logs%20FORMAT%20CSV" --data-binary @data.csv
# → Ok.
# → 1000 rows inserted.
```

### clickhousectl — CLI для ClickHouse (локальный и Cloud)

С 26.x появился единый CLI `clickhousectl` (алиас `chctl`), который объединяет установку версий, управление серверами и выполнение запросов. Не путать с `clickhouse-client` — это разные инструменты.

```bash
# Установка CLI
curl https://clickhouse.com/cli | sh
# → Устанавливает в ~/.local/bin/clickhousectl, создаёт алиас chctl

# Установка и выбор версии ClickHouse (создаёт symlink ~/.local/bin/clickhouse)
clickhousectl local use latest
# → Последний релиз (рекомендуется)

# Управление версиями
clickhousectl local install 26.9          # Последний 26.9.x
clickhousectl local install 26.9.12.8     # Точная версия
clickhousectl local list                   # Установленные
clickhousectl local list --remote         # Доступные для загрузки
clickhousectl local remove 26.9.12.8      # Удалить версию

# Запуск локального сервера (каждый — изолированный каталог данных)
clickhousectl local server start                          # Имя "default"
clickhousectl local server start --name dev               # Имя "dev"
clickhousectl local server start --version stable         # Конкретная версия
clickhousectl local server start --foreground             # В переднем плане
clickhousectl local server start --http-port 8124 --tcp-port 9001  # Явные порты
clickhousectl local server list                           # Список серверов
clickhousectl local server stop default                   # Остановить
clickhousectl local server remove test                    # Удалить и данные

# Выполнение запросов
clickhousectl local client                           # Подключиться к "default"
clickhousectl local client --query "SHOW DATABASES"  # Запрос
clickhousectl local client --queries-file schema.sql  # Файл с запросами
clickhousectl local client --host remote-host --port 9000  # Удалённый сервер

# Инициализация проекта (создаёт структуру папок)
clickhousectl local init
# → clickhouse/{tables,materialized_views,queries,seed}/
```

**Данные хранятся в:** `~/.clickhouse/versions/`, `.clickhouse/servers/<name>/data/`.

**Важно:** `clickhousectl` — CLI для локальной разработки и управления Cloud. Cloud-функционал (`clickhousectl cloud ...`) выходит за рамки этого документа (ограничение по области — облачные технологии). Для продакшен-администрирования используйте `clickhouse-client` + `clickhouse-server` напрямую.

### clickhouse-local: анализ файлов без сервера

```bash
# Подсчёт строк в CSV
clickhouse-local --query "SELECT count() FROM file('data.csv', CSV)"
# → 10000

# Аналитика по Parquet-файлу
clickhouse-local --query "
    SELECT service, count() AS cnt
    FROM file('logs/*.parquet', Parquet)
    GROUP BY service ORDER BY cnt DESC"
# → ┌─service───┬─cnt──┐
# │ api         │ 5000 │
# │ worker      │ 3000 │
# │ scheduler   │ 2000 │
# └─────────────┴──────┘

# Через stdin
cat data.tsv | clickhouse-local --query "SELECT * FROM stdin WHERE x > 100" --format TabSeparated
# → 101	foo
# → 150	bar
# → 200	baz

# С явной схемой
clickhouse-local --query "
    SELECT ts, message
    FROM file('app.log', CSVWithNames, 'ts DateTime, service String, message String')
    WHERE service = 'api'"
# → ┌────────────────────ts─┬─message──────────┐
# │ 2026-01-15 10:30:00     │ User logged in   │
# └─────────────────────────┴──────────────────┘

# Использование S3 (табличная функция доступна и в local)
clickhouse-local --query "SELECT count() FROM s3('http://minio:9000/bucket/*.csv', CSV)"
# → 500000

# Запуск lightweight-сервера (с 26.6): превращает clickhouse-local в доступный по TCP/HTTP
clickhouse-local \
    --listen_host 127.0.0.1 \
    --tcp_port 9000 \
    --http_port 8123 \
    --query "
        SYSTEM START LISTEN TCP;
        SYSTEM START LISTEN HTTP;
        SELECT * FROM url('http://127.0.0.1:8123/?query=SELECT+42', LineAsString);
        SYSTEM STOP LISTEN TCP;
        SYSTEM STOP LISTEN HTTP;
    "
# → 42

# Интерактивно: включить прослушивание
# clickhouse-local
# > SYSTEM START LISTEN TCP;   — Native TCP на 9000
# > SYSTEM START LISTEN HTTP;  — HTTP на 8123
# > SYSTEM STOP LISTEN TCP;    — остановить TCP
# > SYSTEM STOP LISTEN HTTP;   — остановить HTTP
```

**Ограничения `clickhouse-local`:** нет распределённых таблиц, репликации, Keeper, мутаций. Подходит для разового анализа, тестирования запросов и ETL над файлами.

### clickhouse-local как lightweight-сервер (SYSTEM START LISTEN)

С 26.6 `clickhouse-local` можно превратить в сервер, доступный по Native TCP (9000) и HTTP (8123). Полезно для интеграций: другой `clickhouse-client`, веб-приложения (CORS по умолчанию разрешён), приложения.

**Команды:**
- `SYSTEM START LISTEN TCP;` — включить Native TCP (по умолчанию порт 9000)
- `SYSTEM START LISTEN HTTP;` — включить HTTP (по умолчанию порт 8123)
- `SYSTEM STOP LISTEN TCP;` / `SYSTEM STOP LISTEN HTTP;` — остановить

**Порты по умолчанию:** `tcp_port=9000`, `http_port=8123`. Явно задать:
```bash
clickhouse-local --tcp_port 9001 --http_port 8124 --query "SYSTEM START LISTEN HTTP;"
```

**Ограничения:**
- Поддерживает только TCP и HTTP (HTTPS/MYSQL/QUERIES CUSTOM — не поддерживаются, ошибка `UNSUPPORTED_METHOD`)
- Каждое входящее соединение получает отдельную сессию: временные таблицы и настройки интерактивной сессии **не видны** внешним клиентам
- По умолчанию **без аутентификации** (temporary users). Привязка к loopback (`127.0.0.1`, `::1`) рекомендуется. Для аутентификации укажите `users_config` через `--config-file`
- `port=0` (OS-assigned) не совместим с多个 `listen_host` — порт-регистр хранит одно значение
- При сбое стартера слушателей (например, невалидный `listen_host`) слушатели, запущенные в этом же вызове, откатываются целиком (all-or-nothing)
- **Известная проблема (26.6–26.7, фиксировано в #115715):** в неинтерактивном режиме (stdin не TTY) используется `KillingErrorHandler`, который завершает процесс (`std::terminate`) при любом исключении в обработчике соединения — например, при сбросе сокета или одном некорректном пакете. `clickhouse-server` использует `ServerErrorHandler` (лог + продолжение). Если используете `clickhouse-local` как сервер — проверьте, что версия не старше 26.7.4.58. Для daemon-запуска рекомендуется `clickhouse-server` вместо `clickhouse-local`.

### clickhouse-benchmark

```bash
# 100 итераций, параллельность 10
clickhouse-benchmark --query "SELECT count() FROM logs WHERE event_time > now() - INTERVAL 1 DAY" \
    --iterations 100 --concurrency 10
# → Loaded 1 queries.
# → Will execute 100 queries with 10 threads.
# → 
# → Query 1:
# →        min: 42.1 ms
# →        max: 156.3 ms
# →      mean: 58.7 ms
# →      stddev: 12.4 ms
# →      median: 55.2 ms
# →        Q1: 51.3 ms
# →        Q3: 62.8 ms
# →       Q90: 71.4 ms
# →       Q95: 78.9 ms
# →       Q99: 95.2 ms
# → 
# → Total time: 10.2 s

# Сравнение двух запросов (файлы с запросами)
clickhouse-benchmark --query-file q1.sql --iterations 50
clickhouse-benchmark --query-file q2.sql --iterations 50
# → (percentiles для каждого запроса отдельно)
```

Вывод — percentiles времени выполнения (Q1, median, Q3, etc.). Используйте для объективного сравнения оптимизаций: меняйте один параметр и замеряйте baseline.

### Методология нагрузочного тестирования

Систематический подход к измерению производительности ClickHouse:

**Этапы:**
1. **Baseline:** замерить производительность до изменений.
2. **Изолировать переменную:** менять один параметр за раз.
3. **Прогреть кэш:** выполнить запрос 1–2 раза перед замером.
4. **Многократное выполнение:** минимум 50–100 итераций для стабильных percentiles.
5. **Замерить percentiles:** Q1, median, Q3, Q99 — не только среднее.

**Инструменты:**

```bash
# clickhouse-benchmark: одиночный запрос, percentiles
clickhouse-benchmark --query "SELECT count() FROM logs WHERE event_time > now() - INTERVAL 1 DAY" \
    --iterations 100 --concurrency 10
# → Loaded 1 queries.
# → Will execute 100 queries with 10 threads.
# → ...
# → Query 1:
# →        min: 42.1 ms
# →        max: 156.3 ms
# →      median: 55.2 ms
# →       Q99: 95.2 ms

# Сравнение двух версий запроса
clickhouse-benchmark --query-file q1.sql --iterations 100 --concurrency 10
clickhouse-benchmark --query-file q2.sql --iterations 100 --concurrency 10
# → (percentiles для каждого запроса отдельно)

# Замер времени через clickhouse-client
clickhouse-client --time --query "SELECT count() FROM logs"
# → 1000000
# → 
# → real    0.042 sec
# → user    0.018 sec
# → sys     0.004 sec

# Замер через system.query_log (детальные метрики)
SELECT
    query,
    query_duration_ms,
    read_rows,
    read_bytes,
    memory_usage,
    ProfileEvents['ParallelReplicasUsedCount'] AS parallel_replicas
FROM system.query_log
WHERE type = 'QueryFinish'
  AND event_time > now() - INTERVAL 1 HOUR
ORDER BY query_duration_ms DESC
LIMIT 10;
# → ┌─query──────────────────────┬─query_duration_ms─┬─read_rows─┬─read_bytes─┬─memory_usage─┬─parallel_replicas─┐
# │ SELECT count() FROM logs     │              42   │   1000000 │    8000000 │     52428800 │                 0 │
# └──────────────────────────────┴───────────────────┴───────────┴────────────┴──────────────┴─────────────────┘
```

**Что замерять:**

| Метрика | Источник | Целевое значение |
| :--- | :--- | :--- |
| Latency P50/P95/P99 | `clickhouse-benchmark`, `system.query_log` | По SLO (например, P95 < 500 мс) |
| Throughput (QPS) | `system.metrics` `Query` | По SLO |
| Read rows/bytes | `system.query_log` | Минимизировать |
| Memory usage | `system.query_log` | < `max_memory_usage` |
| CPU utilization | `node_exporter` | < 70% среднее |
| Disk I/O | `iostat` | `await` < 10 мс (NVMe) |

**Антипаттерны:**
- Замер на холодном кэше без прогрева.
- Мало итераций (< 10) — высокая дисперсия.
- Параллельная нагрузка при замере одиночного запроса.
- Сравнение запросов с разным объёмом данных.

**ClickBench:** стандартный бенчмарк ClickHouse (набор из 43 запросов по 100M строк). Используется для сравнения конфигураций и версий.

### clickhouse-format

```bash
# Форматирование SQL из файла (в stdout)
clickhouse-format < messy_query.sql > formatted.sql
# → (отформатированный SQL в formatted.sql)

# Форматирование с выводом в stdout
clickhouse-format query.sql
# → SELECT
# →     id,
# →     name
# → FROM table
# → WHERE id > 100
# → ORDER BY name
# → LIMIT 10

# Проверка синтаксиса без вывода (только ошибки)
clickhouse-format --quiet < query.sql
# → (нет вывода при успешной проверке)

# Множественные запросы в одном файле
clickhouse-format --multiquery < multi.sql
# → SELECT 1;
# → SELECT 2;

# Однострочное форматирование для коротких запросов
clickhouse-format --oneline < query.sql
# → SELECT 1

# Форматирование с сохранением комментариев
clickhouse-format --comments < query.sql
# → /* comment */ SELECT 1

# Обфускация вместо форматирования (для безопасной передачи)
clickhouse-format --obfuscate --seed myseed < query.sql
# → SELECT 1 /* ... */

# Подсветка синтаксиса ANSI-escape-последовательностями
clickhouse-format --hilite < query.sql
# → \e[1mSELECT\e[0m ...
```

**Флаги:**

| Флаг | Назначение |
| :--- | :--- |
| `--query` | Форматировать запрос переданный как аргумент |
| `--hilite` / `--highlight` | Добавить ANSI-подсветку синтаксиса |
| `--oneline` | Форматировать в одну строку |
| `--max_line_length N` | Короткие запросы (< N символов) форматировать в одну строку |
| `--comments` | Сохранять комментарии в выводе |
| `--quiet` / `-q` | Проверить синтаксис, не выводить результат |
| `--multiquery` / `-n` | Разрешить несколько запросов в одном файле |
| `--obfuscate` | Обфусцировать вместо форматирования |
| `--seed STR` | Случайное зерно для обфускации |
| `--backslash` | Добавить `\` в конец каждой строки (для копирования в CLI) |
| `--semicolons_inline` | В multiquery-режиме писать точку с запятой в той же строке |

### clickhouse-extract-from-config

Извлекает значения из `config.xml` (или `config.yaml`) по пути. Поддерживает `include_from` и `from_zk` (через `--process-zk-includes`).

```bash
# Извлечь значение из config.xml
clickhouse-extract-from-config --config-file /etc/clickhouse-server/config.xml \
    --key /clickhouse/remote_servers
# → <remote_servers>
# →     <cluster>
# →         <shard>
# →             <internal_replication>true</internal_replication>
# →             <replica>
# →                 <host>ch-01</host>
# →                 <port>9000</port>
# →             </replica>
# →         </shard>
# →     </cluster>
# → </remote_servers>

# Проверить, какие порты слушает сервер
clickhouse-extract-from-config --config-file /etc/clickhouse-server/config.xml \
    --key /clickhouse/tcp_port
# → 9000

# Проверить пользователей (users.xml)
clickhouse-extract-from-config --config-file /etc/clickhouse-server/users.xml \
    --users --key /users/profile/default/networks/ip
# → ::/0

# Обработка from_zk (подключается к ZooKeeper для раскрытия конфига)
clickhouse-extract-from-config --config-file /etc/clickhouse-server/config.xml \
    --process-zk-includes --key /clickhouse/remote_servers

# Не падать на отсутствующие ключи (возвращает пустую строку)
clickhouse-extract-from-config --config-file /etc/clickhouse-server/config.xml \
    --try --key /clickhouse/nonexistent_key
# → (пусто)
```

**Флаги:**

| Флаг | Назначение |
| :--- | :--- |
| `--config-file` / `-c` | Путь к конфигу (обязателен) |
| `--key` / `-k` | Путь к ключу (обязателен) |
| `--process-zk-includes` | Раскрывать `from_zk` элементы через ZooKeeper |
| `--try` | Не предупреждать о пропущенных ключах |
| `--users` | Извлекать из `users.xml` вместо `config.xml` |
| `--stacktrace` | Показывать стек-трейс при ошибке |

### clickhouse-keeper-client

```bash
# Подключение к Keeper (по умолчанию порт 9181)
clickhouse-keeper-client --host keeper-01.internal --port 9181
# → Connecting to keeper-01.internal:9181
# → Welcome to ClickHouse Keeper client!
# → Type 'help' for help.
# → keeper:0>

# Подключение с аутентификацией по паролю
clickhouse-keeper-client --host keeper-01 --port 9181 --password '***'
# → Connected to ZooKeeper at keeper-01:9181 with session_id 123

# Аутентификация по digest-identity (формат "user:password")
clickhouse-keeper-client --host keeper-01 --port 9181 --identity 'keeper:mysecret'
# → Connected to ZooKeeper at keeper-01:9181 with session_id 124

# Подключение из конфигурации (читает <zookeeper><node> из config.xml)
clickhouse-keeper-client --config-file /etc/clickhouse-server/config.xml
# → Использует хост/порт из <zookeeper><node index="1">

# Пароль из конфигурации (приоритет: флаг > env CLICKHOUSE_KEEPER_PASSWORD > <zookeeper><password>)
clickhouse-keeper-client --host keeper-01 --port 9181
# → CLICKHOUSE_KEEPER_PASSWORD=*** clickhouse-keeper-client ...

# Неинтерактивный запрос
clickhouse-keeper-client --host keeper-01 --port 9181 --query "ls /clickhouse/tables"
# → [table1, table2, table3]

# Таймауты сессии и операций
clickhouse-keeper-client --host keeper-01 --port 9181 \
    --connection-timeout 30 --session-timeout 60 --operation-timeout 30
```

**Порядок аутентификации (первый совпадающий выигрывает):**
1. `--password` / `--identity` (флаги CLI)
2. Переменные окружения `CLICKHOUSE_KEEPER_PASSWORD` / `CLICKHOUSE_KEEPER_IDENTITY`
3. `<zookeeper><password>` / `<zookeeper><identity>` в `config.xml` (через `--config-file`)

В интерактивном режиме (zookeeper-совместимые команды):
# ls /clickhouse/tables          — список znode
# → [table1, table2, table3]
# get /clickhouse/tables/...     — содержимое znode
# → <Replica>...</Replica>
# stat /clickhouse/tables/...    — статистика znode
# → cZxid = 0x100000001
# → ctime = Mon Jan 15 10:30:00 UTC 2026
# → ...
# create /path value             — создать znode
# → Created /path
# delete /path                   — удалить znode
# → Deleted /path

### Мосты (bridges)

```bash
# ODBC-мост (для словарей из ODBC-источников)
clickhouse-odbc-bridge --config-file /etc/clickhouse-server/config.xml
# → Starting ODBC bridge...
# → Listening on localhost:9018
# → Ready to accept connections

# Library-мост (для словарей на пользовательских библиотеках)
clickhouse-library-bridge --config-file /etc/clickhouse-server/config.xml
# → Starting Library bridge...
# → Listening on localhost:9019
# → Ready to accept connections
```

Мосты запускаются как отдельные процессы (обычно через systemd или автоматически сервером) и используются источниками словарей `ODBC()` и `EXECUTABLE()`.

## Ограничения и граничные случаи

### clickhouse-client
- **Максимальный размер запроса**: ограничен настройкой `max_query_size` (по умолчанию 1 MiB). Для больших запросов используйте `--multiquery` или загрузку из файла.
- **Таймауты**: `connect_timeout` (по умолчанию 10с), `receive_timeout` / `send_timeout` (по умолчанию 300с). Настраиваются в `config.xml` или через `--connect_timeout`, `--receive_timeout`.
- **Буферизация вывода**: в неинтерактивном режиме вывод буферизируется. Для стриминга используйте `--format=JSONEachRow` или `TabSeparatedRaw`.
- **Пароли в командной строке**: видны в `ps aux`. Используйте переменную окружения `CLICKHOUSE_PASSWORD` или интерактивный ввод.
- **IPv6**: флаг `--host` принимает IPv6 адреса в квадратных скобках: `--host [::1]`.

### clickhouse-local
- **Нет распределённых таблиц**: `Distributed`, `Merge` с удалёнными шардами не работают.
- **Нет репликации и Keeper**: `ReplicatedMergeTree`, `Keeper` — недоступны.
- **Нет мутаций**: `ALTER TABLE ... UPDATE/DELETE` не поддерживаются.
- **Память**: весь датасет загружается в RAM. Для файлов > доступной памяти используйте `clickhouse-server` с `MergeTree`.
- **Параллелизм**: однопоточное выполнение по умолчанию. `max_threads` настраивается через `--max_threads` (начиная с 24.3).
- **Форматы**: не все входные форматы поддерживаются (например, `Protobuf` требует схему).

### clickhouse-benchmark
- **Только SELECT**: DDL/DML запросы не измеряются корректно (побочные эффекты).
- **Кэш**: результаты зависят от состояния кэша страниц ОС и кэша ClickHouse. Обязателен прогрев.
- **Изоляция**: параллельные нагрузки на том же сервере искажают результаты. Используйте выделенный стенд.
- **Статистическая значимость**: < 50 итераций даёт нестабильные percentiles. Минимум 100 для P99.

### HTTP-интерфейс
- **Максимальный POST**: ограничен `http_max_multipart_form_data_size` (по умолчанию 100 MiB).
- **Keep-Alive**: клиенты должны использовать HTTP/1.1 keep-alive для производительности.
- **Таймауты**: `http_receive_timeout`, `http_send_timeout` на сервере (по умолчанию 300с).
- **Сжатие**: `Accept-Encoding: gzip` / `deflate` / `br` для уменьшения трафика.

### clickhouse-keeper-client
- **Только ZooKeeper-совместимые команды**: нет специфичных ClickHouse Keeper команд (например, `reconfig`).
- **Сессия**: таймаут сессии задаётся на сервере (`session_timeout_ms`). Клиент не может его изменить.

### Мосты (bridges)
- **ODBC-мост**: требует установленного `unixODBC` и драйверов для целевых СУБД.
- **Library-мост**: пользовательские библиотеки должны экспортировать функции с C-совместимым ABI.
- **Процессы**: мосты должны быть запущены до использования словарей. Обычно управляются systemd unit'ами.

## Очистка и откат изменений

### Остановка клиентских процессов
```bash
# Завершение интерактивной сессии clickhouse-client
# Нажать Ctrl+D или ввести: EXIT / QUIT

# Принудительное завершение зависшего клиента
pkill -f "clickhouse-client"

# Остановка мостов (если запущены вручную)
pkill -f "clickhouse-odbc-bridge"
pkill -f "clickhouse-library-bridge"
```

### Очистка временных файлов
```bash
# Удаление временных файлов запросов
rm -f /tmp/queries_*.sql /tmp/data_*.csv /tmp/benchmark_*.log

# Очистка кэша clickhouse-local (если использовался --cache)
rm -rf ~/.clickhouse/local_cache/
```

### Откат изменений конфигурации
```bash
# Если clickhouse-extract-from-config показал неверные значения — проверьте config.xml
# Резервная копия перед изменениями:
cp /etc/clickhouse-server/config.xml /etc/clickhouse-server/config.xml.bak

# Восстановление:
cp /etc/clickhouse-server/config.xml.bak /etc/clickhouse-server/config.xml
systemctl reload clickhouse-server
```

### Сброс соединений Keeper
```bash
# При проблемах с Keeper-сессией клиента (по умолчанию порт 9181):
clickhouse-keeper-client --host keeper-01 --port 9181
# В клиенте:
# close
# quit
# Затем переподключиться
```

## Устранение неисправностей

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| `Connection refused` (9000/8123) | Сервер не запущен или слушает localhost | `systemctl status clickhouse-server`; проверить `<listen_host>` в `config.xml` |
| `Authentication failed` | Неверный пользователь/пароль | Проверить `users.xml`/`users.d/`; для SQL-пользователей — `system.users` |
| `Timeout` при подключении | Сеть/DNS/файрвол | Проверить доступность порта (`nc -zv host 9000`), `allow_networks` |
| `clickhouse-local: no such file` | Файл не найден или неверный путь | Указать абсолютный путь; проверить формат (`--format`) |
| `Unknown setting` | Флаг не поддерживается версией | Проверить версию (`clickhouse-client --version`); сверить с документацией |
| `clickhouse-benchmark` показывает высокую дисперсию | Шум среды, кэш холодный | Прогреть кэш, увеличить `--iterations`, изолировать стенд |
| `clickhouse-keeper-client` подключается к ZooKeeper вместо Keeper | Порт 2181 (ZooKeeper) вместо 9181 (Keeper) | Указать `--port 9181`; проверить, что Keeper, а не ZooKeeper |
| `SYSTEM START LISTEN` завершает процесс с abort | `KillingErrorHandler` в неинтерактивном режиме (26.6–26.7) | Обновиться до 26.7.4.58+ или использовать `clickhouse-server` как сервер |
| `clickhouse-format` игнорирует флаги | Неправильный синтаксис (например, `--key-path` вместо `--key`) | Сверить с документацией: `--key`, `--quiet`, `--multiquery`, `--oneline` |

## Сценарии CI/CD (DevOps/SRE)

### Проверка миграций и схемы в пайплайне

```yaml
# Пример: проверка SQL-файла на соответствие стилю ClickHouse перед коммитом
- name: Check SQL formatting
  run: |
    cat migrations/*.sql | clickhouse-format --multiquery --quiet
    # → Выводит только синтаксические ошибки; при успехе — пусто

# Пример: тестирование запроса на локальном дампе данных
- name: Test query against sample data
  run: |
    clickhouse-local --query "
      SELECT count() FROM file('test_data.parquet', Parquet)
    "
    # → Ожидаемое значение из фикстуры
```

### Загрузка данных в CI (без сервера)

```bash
# Генерация тестовых данных и загрузка в staging
clickhouse-local --query "
    SELECT number, now() AS ts
    FROM system.numbers
    LIMIT 1000
" --format Parquet > /tmp/test_data.parquet

# Проверка через HTTP на staging-сервере
curl -X POST "https://staging.clickhouse:8443/?query=INSERT%20INTO%20events%20FORMAT%20Parquet" \
    --data-binary @/tmp/test_data.parquet \
    --user ci --password '${{ secrets.CH_CI_PASSWORD }}'
```

### Health check и диагностика в проде

```bash
# Проверка доступности (health check)
curl -s "http://clickhouse-prod:8123/ping"
# → Ok.

# Проверка репликации (для ReplicatedMergeTree)
clickhouse-client --query "
    SELECT database, table, count() AS replicas
    FROM system.replication_queue
    GROUP BY database, table
"

# Проверка версии клиента и сервера
clickhouse-client --version
clickhouse-client --query "SELECT version()"
```

### Бенчмарк в пайплайне оптимизации

```bash
# Сравнение производительности до/после изменения конфигурации
clickhouse-benchmark --query-file query.sql \
    --iterations 100 --concurrency 4 \
    --timelimit 60 \
    --confidence 4  # 99% доверительный интервал
```

## Лучшие практики

1. **Используйте Native TCP (9000)** для продакшен-клиентов — меньше накладных расходов, чем HTTP.
2. **`clickhouse-local` для разового анализа** файлов — не поднимайте ради этого сервер.
3. **`clickhouse-benchmark` с baseline** — замеряйте производительность до и после оптимизации, меняя один параметр.
4. **`--send_logs_level=debug`** при отладке запросов — логи запроса придут на клиент.
5. **`clickhouse-format`** перед сохранением SQL в репозиторий — единый стиль.
6. **Не храните пароли в командной строке** (видны в `ps`) — используйте `--password` интерактивно или переменные окружения.
7. **`clickhouse-extract-from-config`** для отладки конфигурации вместо ручного чтения XML.
8. **Конфигурация клиента с `connections_credentials`** — централизованное хранение учётных данных, пароль не в `ps`, единый файл с правами 600.
9. **TLS для продакшена**: Native TLS (порт 9440) и HTTPS (8443) вместо plaintext. Настройте `openSSL` в `config.xml` и проверяйте сертификаты (`--secure`).
10. **`clickhousectl` для локальной разработки**, `clickhouse-client` + `clickhouse-server` — для продакшена. Не используйте `clickhouse-local` как замену сервера в проде (нет репликации, Keeper, аутентификации по умолчанию).
11. **Изоляция при бенчмарках**: выделенный стенд, прогрев кэша, минимум 100 итераций, один изменяемый параметр за раз.
12. **`SYSTEM START LISTEN` в `clickhouse-local` только для loopback** без аутентификации — иначе данные доступны любому, кто достигнет порта.

## Дополнительная информация

### Смежные темы

- Основной обзор — **[ClickHouse](./clickhouse.md)**.
- Порты и системные таблицы — **[Мониторинг](./clickhouse-monitoring.md)**.
- Словари (источники через мосты) — **[Словари](./clickhouse-dictionaries.md)**.
- Архитектура и внутреннее устройство — **[Архитектура](./clickhouse-architecture.md)**.
- Кластерное управление — **[Кластеры](./clickhouse-cluster.md)**.
- Безопасность и TLS — **[Безопасность](./clickhouse-security.md)**.
- Операции и обслуживание — **[Операции](./clickhouse-operations.md)**.
- Производительность и оптимизация — **[Производительность](./clickhouse-performance.md)**.
- Резервное копирование — **[Backup](./clickhouse-backup.md)**.
- Kubernetes развёртывание — **[Kubernetes](./clickhouse-kubernetes.md)**.
- Высокая конкурентность — **[High Concurrency](./clickhouse-high-concurrency.md)**.

### Ресурсы

- [Документация: clickhouse-client](https://clickhouse.com/docs/concepts/features/interfaces/client)
- [Документация: clickhouse-local](https://clickhouse.com/docs/concepts/features/tools-and-utilities/clickhouse-local)
- [Документация: HTTP-интерфейс](https://clickhouse.com/docs/concepts/features/http-interface)
- [Документация: clickhouse-format](https://clickhouse.com/docs/concepts/features/tools-and-utilities/clickhouse-format)
- [Документация: clickhouse-benchmark](https://clickhouse.com/docs/concepts/features/tools-and-utilities/clickhouse-benchmark)
- [Документация: clickhouse-keeper-client](https://clickhouse.com/docs/concepts/features/tools-and-utilities/clickhouse-keeper-client)
- [ClickBench бенчмарк](https://github.com/ClickHouse/ClickBench)
- [ClickHouse клиентские библиотеки](https://clickhouse.com/docs/en/interfaces/client-libraries)
