# ClickHouse — Пользовательские функции (UDF)

**Актуально для:** ClickHouse 26.9.x (Stable) / 26.8.x (LTS)

## Определения

- **UDF (User-Defined Function)** — пользовательская функция, определяемая через SQL-выражение и сохраняемая в метаданных ClickHouse. Вызывается как обычная функция.
- **Executable UDF** — функция, реализованная во внешнем исполняемом файле (скрипт, бинарник), вызываемом ClickHouse через stdin/stdout. Настраивается через XML-конфигурацию.
- **Executable pool UDF** — вариант Executable UDF, создающий пул процессов для переиспользования. Снижает накладные расходы на запуск процесса.
- **WASM UDF (WebAssembly UDF)** — функция, написанная на языке, компилируемом в WebAssembly (Rust, C, C++, AssemblyScript), и выполняемая в песочнице внутри процесса ClickHouse.
- **Driver-based UDF** — функция, создаваемая через драйвер (DockerC, GVisorC), который компилирует и запускает код в изолированной среде.
- **system.functions** — системная таблица со списком всех функций (встроенных и пользовательских). Колонки `create_query` и `origin` помечены как устаревшие (obsolete).
- **system.user_defined_functions** — системная таблица с детальной информацией о загрузке и конфигурации Executable UDF (статус загрузки, команда, таймауты, pool_size и т.д.).

## Основные концепции

### Виды UDF

| Вид | Реализация | Кейс |
| :--- | :--- | :--- |
| **SQL UDF** | SQL-выражение | Простые преобразования, вычисляемые колонки |
| **Executable UDF** | Внешний скрипт/бинарник через stdin/stdout | Сложная логика, вызов внешних библиотек |
| **Executable pool UDF** | Пул процессов | Executable UDF с высокой частотой вызовов |
| **WASM UDF** | WebAssembly модуль | Кастомная логика в песочнице (Rust, C/C++, AssemblyScript) |
| **Driver-based UDF** | Драйвер (DockerC, GVisorC) | Автоматическая компиляция и запуск с изоляцией |

### Архитектура выполнения

- **SQL UDF** выполняются внутри движка ClickHouse, как часть плана выполнения запроса.
- **Executable UDF** запускаются как внешние процессы. ClickHouse передаёт данные через stdin и получает результат через stdout. Формат данных задаётся в конфигурации (`format`).
- **Executable pool UDF** создают пул фиксированного количества процессов (`pool_size`, по умолчанию 16), которые переиспользуются для обработки блоков данных. Это значительно снижает накладные расходы по сравнению с `executable`.
- **WASM UDF** загружаются в ClickHouse через таблицу `system.webassembly_modules`. Модуль выполняется внутри серверного процесса в песочнице (изоляция памяти через WASM runtime — wasmtime или wasmedge).
- **Driver-based UDF** создаются через `CREATE FUNCTION ... SOURCE ...` с указанием драйвера. Драйвер компилирует код и создаёт конфигурацию Executable pool UDF автоматически.

### Ограничения SQL UDF

- Имя функции должно быть уникальным (не пересекаться со встроенными).
- Рекурсия запрещена.
- Все переменные в выражении должны быть объявлены в списке параметров.
- Выражение вычисляется при каждом вызове (не кэшируется).
- SQL UDF не поддерживают агрегатные функции внутри себя.

### Настройки сервера для UDF

Для включения WASM UDF в `config.xml`:

```xml
<clickhouse>
    <allow_experimental_webassembly_udf>true</allow_experimental_webassembly_udf>
    <webassembly_udf_engine>wasmtime</webassembly_udf_engine>
</clickhouse>
```

`webassembly_udf_engine` — движок WASM: `wasmtime` (по умолчанию, рекомендуется) или `wasmedge`.

`user_defined_executable_functions_config` — путь к XML-файлу(ам) с конфигурацией Executable UDF. Поддерживает wildcards:

```xml
<clickhouse>
    <user_defined_executable_functions_config>*_function.xml</user_defined_executable_functions_config>
</clickhouse>
```

## Практические сценарии

### Создание SQL UDF

```sql
-- Простая функция
CREATE FUNCTION parse_user_agent AS (ua String) ->
    if(ua LIKE '%Mobile%', 'mobile', if(ua LIKE '%bot%', 'bot', 'desktop'));

-- Функция с несколькими параметрами
CREATE FUNCTION calc_bmi AS (weight Float64, height Float64) ->
    weight / (height * height);

-- С заменой существующей
CREATE OR REPLACE FUNCTION calc_bmi AS (weight Float64, height Float64) ->
    weight / pow(height, 2);

-- На кластере
CREATE FUNCTION parse_user_agent ON CLUSTER '{cluster}' AS (ua String) ->
    if(ua LIKE '%Mobile%', 'mobile', 'desktop');
```

### Использование SQL UDF

```sql
-- В SELECT
SELECT parse_user_agent(user_agent) AS device_type, count()
FROM events
GROUP BY device_type;

-- В WHERE
SELECT * FROM events WHERE calc_bmi(weight, height) > 30;
```

### Управление SQL UDF

```sql
-- Список пользовательских функций
SELECT name, create_query
FROM system.functions
WHERE name NOT IN (SELECT name FROM system.functions WHERE origin = 'System');

-- Удаление
DROP FUNCTION parse_user_agent;

-- На кластере
DROP FUNCTION parse_user_agent ON CLUSTER '{cluster}';
```

### Executable UDF

#### Конфигурация (XML)

```xml
<!-- /etc/clickhouse-server/get_geo_as_json_function.xml -->
<functions>
    <function>
        <type>executable</type>
        <name>get_geo_as_json</name>
        <return_type>String</return_type>
        <argument>
            <type>Float64</type>
            <name>lat</name>
        </argument>
        <argument>
            <type>Float64</type>
            <name>lon</name>
        </argument>
        <format>TabSeparated</format>
        <command>python3 /opt/udf/geo.py</command>
        <!-- optional parameters -->
        <execute_direct>1</execute_direct>
        <check_exit_code>true</check_exit_code>
        <deterministic>true</deterministic>
    </function>
</functions>
```

И скрипт `/opt/udf/geo.py`:

```python
#!/usr/bin/env python3
import sys, json
for line in sys.stdin:
    parts = line.strip().split('\t')
    if len(parts) == 2:
        lat, lon = float(parts[0]), float(parts[1])
        print(json.dumps({"lat": lat, "lon": lon}))
```

```sql
-- Вызов
SELECT get_geo_as_json(lat, lon) FROM events;
```

#### Executable pool UDF (оптимизация)

Для высоконагруженных сценариев используйте тип `executable_pool` с настройкой `pool_size`:

```xml
<functions>
    <function>
        <type>executable_pool</type>
        <name>get_geo_as_json</name>
        <return_type>String</return_type>
        <argument>
            <type>Float64</type>
            <name>lat</name>
        </argument>
        <argument>
            <type>Float64</type>
            <name>lon</name>
        </argument>
        <format>TabSeparated</format>
        <command>python3 /opt/udf/geo.py</command>
        <pool_size>32</pool_size>
        <max_command_execution_time>30</max_command_execution_time>
    </function>
</functions>
```

Параметры для настройки производительности:

| Параметр | Тип | Описание | По умолчанию |
| :--- | :--- | :--- | :--- |
| `pool_size` | UInt64 | Количество процессов в пуле | 16 |
| `max_command_execution_time` | UInt64 | Максимум секунд на обработку блока | 10 |
| `command_termination_timeout` | UInt64 | Секунд до SIGTERM после закрытия pipe | 10 |
| `command_read_timeout` | UInt64 | Таймаут чтения stdout (мс) | 10000 |
| `command_write_timeout` | UInt64 | Таймаут записи stdin (мс) | 10000 |
| `lifetime` | UInt64 | Интервал перезагрузки функции (сек) | 0 (выключено) |
| `stderr_reaction` | String | `none` / `log` / `log_first` / `log_last` / `throw` | `log_last` |
| `check_exit_code` | UInt8 | Проверять exit code | true |

### WASM UDF

WebAssembly UDFs позволяют писать кастомную логику на Rust, C/C++, AssemblyScript или любом языке с компилятором в WASM. Код выполняется в песочнице внутри процесса ClickHouse.

#### Создание WASM UDF (пример на WAT)

```bash
# Установить wabt для компиляции WAT → WASM
apt-get install wabt
```

```wat
;; collatz.wat
(module
  (func $steps (export "steps") (param $n i32) (result i32)
    (local $count i32)
    loop
      (br_if exit (i32.eqz (local.get $n)))
      (i32.add (local.get $count) (i32.const 1))
      local.set $count
      (if (i32.eq (i32.rem_u (local.get $n) (i32.const 2)) (i32.const 0))
        (then (local.set $n (i32.shr_u (local.get $n) (i32.const 1))))
        (else (local.set $n (i32.add (i32.mul (local.get $n) (i32.const 3)) (i32.const 1))))
      )
      br 0
    exit:
    local.get $count
  )
)
```

```bash
# Компилировать WAT → WASM
wat2wasm collatz.wat -o collatz.wasm

# Загрузить модуль в ClickHouse
clickhouse-client --query "
INSERT INTO system.webassembly_modules (name, code)
SELECT 'collatz', base64Decode('$(base64 -w0 collatz.wasm)')
"

# Создать UDF
clickhouse-client --query "
CREATE FUNCTION collatz_steps LANGUAGE WASM ARGUMENTS (n UInt32) RETURNS UInt32 FROM 'collatz' :: 'steps'
"

# Использовать
clickhouse-client --query "SELECT collatz_steps(27)"
```

#### Синтаксис создания WASM UDF

```sql
CREATE [OR REPLACE] FUNCTION function_name
LANGUAGE WASM
FROM 'module_name' [:: 'source_function_name']
ARGUMENTS ( [name type[, ...]] | [type[, ...]] )
RETURNS return_type
[ABI ROW_DIRECT | ABI BUFFERED_V1 | ABI ASSEMBLYSCRIPT]
[DETERMINISTIC]
[SHA256_HASH 'hex']
[SETTINGS key = value[, ...]];
```

Поддерживаемые ABI:
- **ROW_DIRECT** — прямое сопоставление типов, обработка построчно. Только числовые типы (`Int32`, `UInt32`, `Int64`, `UInt64`, `Float32`, `Float64`). Строки не поддерживаются.
- **BUFFERED_V1** — обработка блоками с сериализацией. Поддерживает любые типы данных через сериализацию (MsgPack, JSONEachRow, CSV, TSV, RowBinary и др.).
- **ASSEMBLYSCRIPT** — row-by-row для модулей AssemblyScript. Поддерживает числовые типы и `String`.

#### Настройки WASM UDF

| Setting | Описание | По умолчанию |
| :--- | :--- | :--- |
| `webassembly_udf_max_fuel` | Лимит топлива (fuel) на вызов | 0 (без лимита) |
| `webassembly_udf_max_memory` | Лимит памяти на экземпляр (байты) | 0 (без лимита) |
| `webassembly_udf_max_input_block_size` | Максимум строк в блоке для WASM UDF | 0 (обрабатывать все) |
| `webassembly_udf_max_instances` | Максимум параллельных экземпляров на функцию | — |

### Driver-based UDF

Драйверы позволяют создавать UDF из inline-кода с автоматической компиляцией и изоляцией:

```sql
-- UnsafeC — прямо на хосте (без изоляции)
CREATE FUNCTION my_func
SOURCE UnsafeC
LANG C
CODE '#include <math.h> double f(double x) { return sqrt(x); }'
ARGUMENTS (a Float64)
RETURNS Float64;

-- DockerC — в изолированном Docker-контейнере
CREATE FUNCTION my_func
SOURCE DockerC
LANG C
CODE '#include <math.h> double f(double x) { return sqrt(x); }'
ARGUMENTS (a Float64)
RETURNS Float64;

-- GVisorC — через gVisor runsc runtime
CREATE FUNCTION my_func
SOURCE GVisorC
LANG C
CODE '#include <math.h> double f(double x) { return sqrt(x); }'
ARGUMENTS (a Float64)
RETURNS Float64;
```

Драйверы:
- **UnsafeC** — компилирует и запускает код прямо на хосте. Никакой изоляции — только для тестирования и доверенной среды.
- **DockerC** — компилирует и запускает в Docker (`--network=none --read-only --cap-drop=ALL --security-opt=no-new-privileges`, лимиты памяти/CPU/PID). Эмулирует `executable_pool`.
- **GVisorC** — вариант с gVisor `runsc` runtime.

## Операции и команды

### Мониторинг UDF

```sql
-- Все UDF с статусом загрузки
SELECT name, load_status, type, command, return_type, argument_types
FROM system.user_defined_functions
FORMAT Vertical;

-- Неудачные загрузки
SELECT name, loading_error_message
FROM system.user_defined_functions
WHERE load_status = 'Failed';

-- WASM-модули
SELECT name, lower(hex(reinterpretAsFixedString(hash))) AS sha256
FROM system.webassembly_modules;

-- Все UDF в system.functions
SELECT name, is_aggregate, create_query
FROM system.functions
WHERE origin = 'SQLUserDefined' OR origin = 'ExecutableUserDefined';
```

### Удаление UDF

```sql
-- SQL UDF
DROP FUNCTION calc_bmi;

-- На кластере
DROP FUNCTION calc_bmi ON CLUSTER '{cluster}';

-- Удалить WASM-модуль
DROP FUNCTION collatz_steps;
```

## Устранение неисправностей

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| `UNKNOWN FUNCTION` | Функция не создана или не на всех узлах кластера | Проверить `system.functions`; создать `ON CLUSTER` |
| `Function already exists` | Дубликат имени | `CREATE OR REPLACE FUNCTION` |
| Рекурсия | UDF вызывает себя | Переписать без рекурсии |
| Executable UDF не вызывается | Скрипт не исполняемый / неверный путь / неверный XML | Проверить права (`chmod +x`), путь в config, структуру XML (`<functions><function>`) |
| `ExecutableUserDefinedFunction error` | Ошибка выполнения скрипта | Проверить `stderr_reaction` в конфиге; посмотреть логи ClickHouse |
| `WASM_ERROR` | Ошибка выполнения WASM-модуля | Проверить `webassembly_udf_max_memory` и `webassembly_udf_max_fuel`; логи сервера |
| `Module not found` | WASM-модуль не загружен | Проверить `system.webassembly_modules`; загрузить через `INSERT INTO system.webassembly_modules` |
| Медленная UDF | Вызов на каждую строку | Перенести логику в `MATERIALIZED`-колонку; использовать `executable_pool` вместо `executable` |
| `Root element doesn't have the corresponding root element` | В XML-конфиге неверный корневой элемент | Использовать `<functions>` как корень, а не `<clickhouse>` |
| Несоответствие типов WASM | Типы аргументов не совпадают с WASM-экспортом | Проверить сигнатуру экспортированной функции в модуле |

## Лучшие практики

1. **SQL UDF** — для простых преобразований; не злоупотреблять в `WHERE` (вычисляется на каждую строку).
2. **`CREATE OR REPLACE`** — для безопасного обновления функций.
3. **`ON CLUSTER`** — создавать на кластере, чтобы функция была на всех узлах.
4. **Executable UDF** — только когда SQL недостаточен; помнить о накладных расходах на запуск процесса.
5. **`executable_pool`** — для высоконагруженных сценариев; настраивать `pool_size` и `max_command_execution_time`.
6. **WASM UDF** — для сложной логики, требующей производительности близкой к нативной; использовать `wasmtime` engine.
7. **Driver-based UDF** — использовать `DockerC` или `GVisorC` для изоляции; `UnsafeC` только в тестах.
8. **Документировать** — сохранять `create_query` из `system.functions` в репозиторий.
9. **Версионирование** — хранить UDF-скрипты и конфиги в Git вместе с миграциями схемы.
10. **Мониторинг** — регулярно проверять `system.user_defined_functions` на `load_status = 'Failed'`.

## Дополнительная информация

### Смежные темы

- Вычисляемые колонки (DEFAULT/MATERERIALIZED/ALIAS) — **[Эволюция схемы](./clickhouse-schema-evolution.md)**.
- Оптимизация запросов — **[Производительность](./clickhouse-performance.md)**.
- Управление кластером — **[Кластер](./clickhouse-cluster.md)**.
- Бэкапы — **[Бэкапы](./clickhouse-backup.md)**.

### Ресурсы

- [Документация: User-Defined Functions](https://clickhouse.com/docs/sql-reference/user-defined-functions)
- [Документация: Executable UDF](https://clickhouse.com/docs/sql-reference/user-defined-functions/executable-udf)
- [Документация: WebAssembly UDF](https://clickhouse.com/docs/reference/functions/regular-functions/wasm_udf)
- [Документация: system.user_defined_functions](https://clickhouse.com/docs/reference/system-tables/user_defined_functions)
- [GitHub: clickhouse-wasm-udf-rs (Rust SDK)](https://github.com/ClickHouse/clickhouse-wasm-udf-rs)