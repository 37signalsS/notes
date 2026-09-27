# VRL (Vector Remap Language)

## Определения

**VRL (Vector Remap Language)** — предметно-ориентированный язык (DSL), выражение-ориентированный, с сильной типизацией, предназначенный для безопасной и высокопроизводительной трансформации данных (логов, метрик, трассировок) внутри Vector.

**Ключевые принципы (Safety + Performance):**

*   **Компиляция в нативный код:** VRL-программы компилируются в **нативный код Rust** на этапе запуска Vector (AOT — ahead-of-time). Это даёт производительность, близкую к чистому Rust: нет виртуальной машины, FFI-вызовов или накладных расходов на сериализацию между событиями. Каждое выражение компилируется в машинные инструкции.
*   **Progressive type safety:** типы выводятся по мере выполнения программы. После того как тип поля установлен (назначен или выведен из результата функции), последующие обращения к нему проверяются компилятором статически; несоответствие типов блокирует запуск Vector до исправления.
*   **Fail safety:** любая функция, способная вернуть ошибку (fallible), обязана явно обрабатывать эту ошибку (суффикс `!` или присваивание кортежа). VRL не скомпилируется, пока ошибка не обработана.
*   **Отсутствие сборщика мусора (GC):** нет GC-пауз и накопления памяти между событиями. Память выделяется и освобождается детерминировано для каждого события.
*   **Statelessness:** VRL — язык без состояния: каждая программа обрабатывает ровно одно событие; каждое выражение возвращает значение. Нет глобальных переменных, статических полей или побочных эффектов между событиями.
*   **Ограниченность конструкции:** VRL не является языком общего назначения: нет циклов, классов, модулей, пользовательских функций и произвольного ввода-вывода (кроме отдельных функций, например `http_request`). Это сделано намеренно, чтобы исключить медленные или непредсказуемые скрипты и обеспечить предсказуемую производительность.
*   **Безопасность по умолчанию:** VRL работает в песочнице. Запрещены бесконечные циклы, произвольный доступ к файловой системе (кроме разрешённых функций) и недетерминированные операции.

**Аналогия для понимания:** если традиционные языки скриптов — это «универсальный швейцарский нож», то VRL — это специализированный хирургический инструмент, который всегда делает один тип операции, но делает её быстро, безопасно и предсказуемо.

---

## Основные концепции

### Модель обработки событий

VRL работает в контексте одного события (Event). Событие представлено как иерархическая структура данных (объект), доступ к полям которой осуществляется через точку:

*   `.` — текущее событие целиком.
*   `.field` — доступ к полю `field`.
*   `.field[0]` — доступ к элементу массива по индексу.
*   `.service.name` — навигация по вложенным полям.
*   `del(.field)` — удаление поля.
*   `@timestamp` — системные метаданные Vector (системные поля начинаются с `@`).

**Важная деталь:** точка (`.`) в начале выражения — это сокращение для `..` (текущее событие). Внутри замыканий (closures) `.` ссылается на аргумент замыкания, а не на событие. Для доступа к событию внутри замыкания используется `$` (например, `$.message`).

Программа — последовательность выражений, разделённых переносами строк или `;`.

**Жизненный цикл одного события в VRL:**

1.  Vector передаёт событие в VRL-программу.
2.  VRL компилирует программу в нативный код (при первом запуске или изменении файла).
3.  Выполняются выражения сверху вниз.
4.  Если встречается `abort` или fallible-ошибка с `!` — событие отбрасывается (или отправляется в `dropped` выход).
5.  Итоговое значение `.` передаётся в следующий компонент Vector.

### Операторы и управляющие конструкции

| Конструкция | Пример | Описание |
| :--- | :--- | :--- |
| Присваивание | `.level = string!(.level)` | Запись значения в поле. |
| Составное присваивание | `.count += 1` | То же, что `.count = .count + 1`. |
| Условный оператор | `if .level == "error" { … } else { … }` | Условный переход. С 2026 г. `else`/`else if` можно начинать с новой строки. |
| Оператор `??` (coalescing) | `.msg ?? "default"` | Значение по умолчанию, если поле `null`. |
| Логика и сравнение | `==`, `!=`, `<`, `>`, `<=`, `>=`, `&&`, `||`, `!` | Сравнение и булева логика. |
| `abort` | `abort` | Завершить программу для этого события (событие отбрасывается). |
| `assert` | `assert!(condition, "msg")` | Останавливает программу с ошибкой, если условие ложно. |
| Комментарии | `# …` | Строковый комментарий. |

**Особенность `else` (2026+):** раньше `else` и `else if` требовались на той же строке, что и закрывающая фигурная скобка. Начиная с v0.55, можно писать:

```vrl
if .level == "error" {
    .status = "critical"
}
else if .level == "warn" {
    .status = "warning"
}
else {
    .status = "ok"
}
```

### Типы данных

VRL оперирует типовой системой из девяти типов:

| Тип | Запись/пример | Примечание |
| :--- | :--- | :--- |
| `string` (`bytes`) | `"foo"`, `s'raw'` | UTF-8 строки; `s'...'` — raw-строки без обработки escape-последовательностей. |
| `integer` | `42` | 64-битное знаковое целое (i64). |
| `float` | `4.2` | 64-битное число с плавающей точкой (f64). |
| `boolean` | `true`, `false` | Логический тип. |
| `timestamp` | `@timestamp`, `now()` | Временная метка с наносекундной точностью. |
| `null` | `null` | Отсутствие значения. |
| `object` | `{ "a": 1 }` | Ассоциативный массив (хеш-таблица). |
| `array` | `[1, 2, 3]` | Вектор (динамический массив). |
| `regex` | `r'^foo'` | Скомпилированное регулярное выражение. |

**Приведение типов:**

*   **Принудительное (unwrapping):** `string!(.x)`, `int!(.x)` — если значение не может быть приведено, программа прерывается (аналог `abort`).
*   **Безопасное (fallible):** `to_string(.x)`, `to_int(.x)` — возвращают кортеж `(value, err)`. Если преобразование невозможно, `value` будет `null`, а `err` — описанием ошибки.

**Пример:**
```vrl
# Принудительное приведение — упадёт, если .user_id не число
.user_id_int = int!(.user_id)

# Безопасное приведение — обрабатываем ошибку
.user_id_int, err = to_int(.user_id)
if err != null {
    log("Invalid user_id: " + string!(.user_id), level: "warn")
    abort
}
```

**Progressive type safety в действии:**
```vrl
.level = "info"        # .level теперь строка (тип выведен)
.level = to_upper(.level)  # OK: строка → строка
.level = 42            # ОШИБКА КОМПИЛЯЦИИ: несоответствие типов
```

### Обработка ошибок и Fallible-функции

В VRL функции делятся на два типа:

1.  **Обычные (infallible) функции** — всегда возвращают значение без ошибки. Примеры: `upcase`, `downcase`, `floor`, `round`.
2.  **Fallible-функции** — могут вернуть ошибку; в сигнатуре обозначаются суффиксом `!`. Примеры: `parse_json!`, `parse_syslog!`, `to_int`, `get_enrichment_table_record`.

**Способы обработки ошибок:**

*   **Вызов с `!` (abort):** при ошибке программа прерывается для текущего события (событие отправляется в `dropped` или лог ошибок либо отбрасывается):

    ```vrl
    . = parse_json!(string!(.message))
    ```

*   **Ручная обработка (tuple assignment):** присваивание с возвратом ошибки без прерывания:

    ```vrl
    value, err = parse_json(.message)
    if err != null {
        .error = err
    }
    ```

*   **Оператор `??`** — значение по умолчанию при `null`.
*   **`assert` / `assert_eq`** — остановка программы при нарушении условия.

**v0.55+ — группировка ошибок:** компиляция VRL выводит **все** необработанные ошибки за один проход, а не останавливается на первой. Это ускоряет отладку сложных скриптов.

### Итерации

VRL не имеет циклов `for`/`while`, но поддерживает итерацию по коллекциям через функции с замыканиями:

*   `map_keys` / `map_values` — трансформация ключей или значений.
*   `filter` — фильтрация элементов коллекции.
*   `for_each` — применение замыкания к каждому элементу (объект/массив).

Пример (переименование ключей, рекурсивно):

```vrl
.kubernetes.annotations = map_keys(.kubernetes.annotations, recursive: true) -> |key| {
    replace(key, ".", "_")
}
```

**Производительность итераций:** замыкания компилируются в оптимизированный цикл на Rust. Для небольших коллекций (<100 элементов) overhead минимален. Для больших массивов (>10 000 элементов) предпочитайте векторные операции (`tally`, `unique`), если это возможно.

### Возможности и лимиты (2026)

| Характеристика | Описание |
| :--- | :--- |
| **Типизация** | Строгая, выводится автоматически или принудительно (`string!`, `int!`). |
| **Типы данных** | String/Bytes, Integer, Float, Boolean, Timestamp, Object, Array, Null, Regex. |
| **Трансформации** | Рекурсивный обход структур (`map_keys`), глубокое объединение объектов. |
| **JQ-совместимость** | Функции `to_entries`, `from_entries`, `compact` (добавлены в 2025–2026). |
| **Ограничения** | Нет циклов `for/while` (вместо них — итераторы замыканий), нет пользовательских функций, нет глобального состояния. |
| **Стек вызовов** | Ограничен глубиной вложенности замыканий (обычно 64 уровня). |
| **Размер события** | Практический лимит — ~1 МБ на событие (ограничение памяти Vector). |
| **Время компиляции** | Программа компилируется один раз при старте; последующие события выполняются без overhead компиляции. |

### Библиотека функций (Актуально на v0.57)

| Категория | Ключевые функции |
| :--- | :--- |
| **Парсинг** | `parse_json`, `parse_syslog`, `parse_common_log`, `parse_grok`, `parse_tokens`, `parse_yaml` (добавлена в 2026), `parse_regex`, `parse_url`, `parse_user_agent`, `parse_logfmt`, `parse_csv`, `parse_proto`. |
| **Кодирование/декодирование** | `encode_json`, `encode_csv` (new), `encode_logfmt`, `encode_proto` (2026), `encode_key_value`, `encode_gzip`, `decode_gzip`, `encode_zstd`, `decode_zstd`, `encode_base64`, `decode_base64`. |
| **Манипуляция объектами** | `map_keys`, `map_values`, `to_entries`, `from_entries` (2026), `merge` (shallow/deep), `flatten`, `compact`, `unflatten`. |
| **Массивы** | `push`, `pop`, `append`, `unique`, `chunks`, `zip`. |
| **Итерация/запросы** | `for_each`, `filter`, `values`, `find`. |
| **Время** | `now`, `format_timestamp`, `parse_timestamp`, `to_unix_timestamp`, `from_unix_timestamp`. |
| **Сравнение/математика** | `includes`, `contains`, `starts_with`, `ends_with`, `match`, `round`, `ceil`, `floor`, `mod`, `tally`. |
| **Строковые операции** | `split`, `slice`, `replace`, `truncate`, `upcase`, `downcase`, `strip_ansi_escape_codes`, `redact`. |
| **Хэширование и безопасность** | `md5`, `sha1`, `sha2`, `sha3`, `crc`, `xxhash`, `uuid_v4`, `uuid_v7` (2026), `decrypt`, `encrypt`, `encrypt_ip`, `decrypt_ip` (2026). |
| **Специальные 2026** | `http_request` (выполнение HTTP-запроса из VRL), `haversine` (расстояние на сфере), `redact` (маскирование PII). |
| **Мониторинг Vector** | `get_vector_metric`, `find_vector_metrics`, `aggregate_vector_metrics` (доступ к внутренним метрикам Vector). |
| **Enrichment** | `get_enrichment_table_record`, `find_enrichment_table_records`; с 2026 добавлен фильтр дат `from`/`to` и wildcard-сопоставление. |
| **Уверения/тесты** | `assert`, `assert_eq` (fallible). |
| **Разное** | `get_env_var`, `get_hostname`, `basename`, `dirname`, `split_path` (2026+). |

### Производительность и модель памяти

**Нет GC-пауз:** VRL выделяет память для каждого события на стеке или в пуле объектов. После обработки события вся память освобождается атомарно. Это критично для high-load пайплайнов, где GC-паузы на других языках (Java, Go) могут достигать сотен миллисекунд.

**Размер события и лимиты:**

*   Практический лимит размера одного события — ~1 МБ (конфигурируется через `max_event_size` в Vector).
*   Сложные регулярные выражения в `parse_grok`/`parse_regex` могут потреблять много CPU. Для высоконагруженных пайплайнов профилируйте VRL через `component_latency_seconds`.

**Советы по производительности:**

1.  **Избегайте `parse_grok` там, где достаточно `parse_json` или `parse_syslog`.** Специализированные парсеры работают на порядок быстрее.
2.  **Кэшируйте enrichment-таблицы в памяти**, а не делайте HTTP-запросы для каждого события.
3.  **Используйте `??` вместо `if exists`** для значений по умолчанию — короче и быстрее.
4.  **Не пересоздавайте объекты без необходимости.** Изменение полей in-place эффективнее, чем создание нового объекта через `merge`.

### Безопасность и изоляция

VRL работает в песочнице с жёсткими ограничениями:

*   **Нет произвольного I/O:** только разрешённые функции (`http_request`, чтение enrichment-таблиц).
*   **Ограничение ресурсов:** Vector ограничивает время выполнения VRL-программы (timeout) и память. При превышении — событие отбрасывается.
*   **Нет состояния между событиями:** невозможно «утечь» данные из одного события в следующий.
*   **Шаблонизация (Template Confinement, v0.57):** sinks, принимающие `{{ field }}` в путях/заголовках, отклоняют шаблоны без буквального префикса, предотвращая path traversal.

### Синтаксические улучшения 2026 (v0.55–v0.57)

*   **`find` теперь возвращает `null`** при отсутствии совпадения (ранее `-1`) — ломающее изменение: проверьте код, который ветвился на `find(x) < 0`.
*   **`else`/`else if`** можно писать на новой строке (вместо обязательного `} else {` на одной строке).
*   **Строковые литералы** поддерживают юникод-экранирование `\u{...}` (например, `"\u{1F30E}"`) с проверкой при компиляции.
*   **Компилятор** выводит полный список ошибок за один проход (2026+).
*   **Поверхность функций:** Vector-специфичные функции (метрики и т.д.) теперь доступны и в независимом CLI `vector vrl`, и в кодек-трансформациях VRL.

### Применение VRL в Vector

*   **`remap` transform** — основное место использования VRL (парсинг, изменение, очистка полей). Настройка: `source` или `file` (внешний `.vrl`-файл), `drop_on_error`, `reroute_dropped`, `timezone`.
*   **`filter` / `route` transforms** — VRL-условия: тип `vrl` с булевым выражением (`condition: .status != 200`).
*   **`delay` transform** — выражение задержки на базе VRL.
*   **HTTP-client / auth-стратегии:** HTTP client-источники принимают VRL-выражения в параметрах запроса и body; в кастомных auth-стратегиях VRL может записывать значение в auth-контекст (`%field = value`).
*   **Unit-тесты** — проверка результатов через VRL-условия в секции `[[tests]]` (assertы и `expected_event_count`).

### Внешние VRL-файлы и live-перезагрузка

*   `file: "/paths/program.vrl"` в `remap` — вынести программу во внешний файл.
*   `--watch-config` — слежение за изменениями внешних VRL-файлов.
*   `SIGHUP` — перезагрузка внешних VRL-файлов без рестарта (начиная с 2026 г.).

---

## Практические сценарии

### Пример комплексной трансформации

```vrl
# 1. Принудительный парсинг JSON с обработкой ошибок
. = parse_json!(string!(.message))

# 2. Нормализация уровней логирования (case-insensitive)
.level = upcase(string!(.level) ?? "INFO")

# 3. Работа с jq-совместимыми структурами (v0.56+)
# Превращаем объект labels в массив ключ-значение для специфичных sink-ов
if exists(.labels) {
    .labels_array = to_entries(.labels)
}

# 4. Рекурсивная очистка метаданных Kubernetes
if exists(.kubernetes.annotations) {
    .kubernetes.annotations = map_keys(.kubernetes.annotations, recursive: true) -> |key| {
        # Заменяем точки на подчеркивания для OpenSearch
        replace(key, ".", "_")
    }
}

# 5. Маскирование PII (Персональных данных)
if exists(.user_email) {
    .user_email = md5(string!(.user_email))
}

# 6. Удаление временных полей и метаданных
del(.internal_id)
del(.@raw)
```

### Итерация и фильтрация массивов

```vrl
# Оставляем только элементы, не равные nil
.event_ids = filter(array(.events)) -> |_index, value| {
    value != nil
}

# Подсчёт вхождений строк в массиве (tally)
.counts = tally(array(.tags))
```

### Обработка ошибок при обогащении через Enrichment Tables

```vrl
row, err = get_enrichment_table_record(
    table: "geoip",
    condition: { "ip": .user_ip }
)
if err == null {
    .geo = row
} else {
    log("Запись не найдена для " + string!(.user_ip), level: "warn")
}
```

Детальные примеры использования в реальных конфигурациях: **[Practical Scenarios](./practical_scenarios.md)**.

### Сценарий 1: Парсинг логов systemd-journald

**Задача:** Vector собирает логи через `journald` source. Логи имеют формат с ключами journald (`PRIORITY`, `SYSLOG_IDENTIFIER`, `_PID` и т.д.). Необходимо нормализовать их в единый формат для Loki.

**Конфигурация Vector:**

```toml
[sources.journald]
type = "journald"
include_units = ["ssh.service", "cron.service", "nginx.service"]

[transforms.normalize_journald]
type = "remap"
inputs = ["journald"]
source = '''
# Journald помещает сообщение в .message, а приоритет в виде числа — в .priority
# Нормализуем приоритет в текстовый уровень
.level = case .priority {
    0 => "emerg",
    1 => "alert",
    2 => "crit",
    3 => "err",
    4 => "warning",
    5 => "notice",
    6 => "info",
    7 => "debug",
    else => "info"
}

# Формируем сервис из SYSLOG_IDENTIFIER или MESSAGE
.service = .systemd_unit ?? .SYSLOG_IDENTIFIER ?? .MESSAGE

# Удаляем служебные поля journald
del(.["_PID", "_UID", "_GID", "_COMM", "_EXE", "priority", "SYSLOG_IDENTIFIER", "MESSAGE"])
'''
```

**Валидация:**
```bash
vector validate /etc/vector/vector.yaml
vector tap normalize_journald
```

### Сценарий 2: Парсинг auth.log (SSH, sudo)

**Задача:** Из plain-text логов `/var/log/auth.log` извлекать удачные/неудачные SSH-логины и попытки sudo.

**Формат auth.log (syslog RFC 5424):**
```
Jan 15 10:23:45 web-01 sshd[1234]: Accepted publickey for admin from 192.168.1.10 port 22 ssh2
Jan 15 10:24:01 web-01 sudo: pam_unix(sudo:session): session opened for user root by admin(uid=1000)
Jan 15 10:25:00 web-01 sshd[1235]: Failed password for invalid user test from 1.2.3.4 port 22 ssh2
```

**VRL-программа:**

```vrl
# Парсим стандартный syslog с помощью parse_syslog
. = parse_syslog!(.message)

# Определяем тип события
if .app == "sshd" {
    if includes(.message, "Accepted") {
        .event_type = "ssh_success"
        # Извлекаем пользователя: "for <user>"
        .user = capture(.message, r'for (\S+)')?.[0] ?? "unknown"
        .source_ip = capture(.message, r'from (\S+)')?.[0] ?? "unknown"
    } else if includes(.message, "Failed password") {
        .event_type = "ssh_failed"
        .user = capture(.message, r'for (?:invalid user )?(\S+)')?.[0] ?? "unknown"
        .source_ip = capture(.message, r'from (\S+)')?.[0] ?? "unknown"
    }
} else if .app == "sudo" {
    .event_type = "sudo_session"
    .user = capture(.message, r'session opened for user (\S+)')?.[0] ?? "unknown"
}

# Нормализуем время (syslog не содержит года — добавляем текущий)
if !exists(.year) {
    .timestamp = parse_timestamp!(strftime(now(), "%Y ") + .timestamp, "%Y %b %d %H:%M:%S")
}
```

**Проверка:**
```bash
vector tap auth_transform
```

### Сценарий 3: Парсинг логов Nginx (access_log)

**Задача:** Преобразовать текстовый access_log Nginx в структурированный JSON.

**Формат лога:**
```
192.168.1.10 - - [15/Jan/2026:10:23:45 +0000] "GET /api/v1/users HTTP/1.1" 200 1234 "-" "curl/7.68.0"
```

**VRL-программа:**

```vrl
# Определяем шаблон (лучше вынести в переменную или использовать parse_grok)
# Для стабильного формата можно использовать regex + capture
pattern = r'^(?P<source_ip>\S+) \S+ \S+ \[(?P<timestamp>[^\]]+)\] "(?P<method>\S+) (?P<path>\S+) \S+" (?P<status>\d+) (?P<bytes>\d+) "(?P<referer>[^"]*)" "(?P<user_agent>[^"]*)"$'

match = match(.message, pattern)
if match != null {
    .source_ip = match.source_ip
    .timestamp = parse_timestamp!(match.timestamp, "02/Jan/2006:15:04:05 -0700")
    .http_method = match.method
    .url = match.path
    .status = int!(match.status)
    .bytes_sent = int!(match.bytes)
    .referer = match.referer
    .user_agent = match.user_agent
    .event_type = "http_access"
} else {
    # Если строка не совпала — помечаем и отбрасываем или отправляем в отдельный sink
    .parse_error = true
    abort
}
```

**Альтернатива через `parse_grok` (если паттерн уже определён):**
```vrl
. = parse_grok!(.message, "%{IPORHOST:source_ip} %{USER:ident} %{USER:auth} \[%{HTTPDATE:timestamp}\] \"%{WORD:method} %{DATA:path} HTTP/%{NUMBER:version}\" %{NUMBER:status} %{NUMBER:bytes}")
```

### Сценарий 4: Обогащение логов ядра (kernel/dmesg)

**Задача:** Добавить в логи ядра (kern.log) контекст хоста и метрики системы.

```vrl
# Предполагаем, что источник Vector уже добавил hostname
# Добавляем системные метрики через get_vector_metric
.cpu_usage = get_vector_metric!("vector_process_cpu_seconds_total")?[0] ?? null
.memory_usage = get_vector_metric!("vector_process_memory_bytes")?[0] ?? null

# Классифицируем уровень критичности
if includes(.message, r'\[.*\].*(error|fail|critical|panic)') {
    .severity = "critical"
} else if includes(.message, r'\[.*\].*(warn|warning)') {
    .severity = "warning"
} else {
    .severity = "info"
}

# Извлекаем имя модуля ядра (если есть)
.module = capture(.message, r'(\w+):')?.[0] ?? "kernel"
```

### Сценарий 5: Маскирование чувствительных данных в системных логах

**Задача:** Скрыть внутренние IP-адреса и hostnames в логах перед отправкой в центральное хранилище.

```vrl
# Маскируем внутренние IP-адреса (RFC 1918)
.message = replace(.message, r'\b(10\.|172\.(1[6-9]|2\d|3[01])\.|192\.168\.)\d{1,3}\.\d{1,3}\b', "10.0.0.0")

# Маскируем hostnames домена corp.local
.message = replace(.message, r'\b([a-z0-9-]+\.)*corp\.local\b', "hidden.corp.local")

# Маскируем секреты, попавшие в stdout приложений
.message = redact(.message,
    patterns: [
        r'(?i)(password|secret|token|api_key)\s*[=:]\s*\S+',
        r'\b[A-Za-z0-9._%+-]+@(corp\.local|internal)\b'
    ],
    redact: "[REDACTED]"
)
```

### Сценарий 6: Нормализация уровней логирования из mixed sources

**Задача:** Разные приложения используют разные регистры и словари уровней (`ERROR`, `Err`, `error`, `CRITICAL`, `fatal`). Привести к единому стандарту.

```vrl
level = downcase(string!(.level ?? .severity ?? .priority ?? "info"))

.level = case level {
    "emerg" => "emergency",
    "alert" => "alert",
    "crit" => "critical",
    "critical" => "critical",
    "err" => "error",
    "error" => "error",
    "warning" => "warning",
    "warn" => "warning",
    "notice" => "notice",
    "info" => "info",
    "debug" => "debug",
    "trace" => "trace",
    "fatal" => "critical",
    else => "info"
}
```

### Сценарий 7: Выявление аномалий по частоте ошибок

**Задача:** На стороне Vector подсчитывать количество ERROR-логов за последние 60 секунд и снижать уровень логирования при всплеске (throttling).

```vrl
# Используем встроенные метрики Vector для оценки нагрузки
error_rate = get_vector_metric!("component_received_events_total{component_id=\"~\", level=\"error\"}")?[0] ?? 0

if error_rate > 1000 {
    # Снижаем детализацию: отбрасываем DEBUG/INFO
    if .level == "debug" || .level == "info" {
        abort
    }
}

# Или динамическое сэмплирование на основе внешней переменной
sampling_rate = 0.1  # Можно вынести в enrichment table
if .level == "info" && random_float() > sampling_rate {
    abort
}
```

---

## Траблшутинг

### Типичные ошибки компиляции

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `unhandled fallible function` | Вызов fallible-функции без `!` или без кортежа | Добавьте `!` или `(value, err) = func(...)` |
| `type mismatch` | Присваивание значения несовместимого типа | Проверьте тип поля через `type()` или используйте приведение |
| `field does not exist` | Обращение к несуществующему полю | Используйте `exists(.field)` или `?.field` |
| `unresolved reference` | Использование переменной до присваивания | Убедитесь, что переменная объявлена в текущей области видимости |
| `regex compilation failed` | Неверное регулярное выражение | Проверьте синтаксис regex через `vector vrl` REPL |

### Диагностика во время выполнения

```bash
# Валидация конфигурации
vector validate --deny-warnings /etc/vector/vector.yaml

# Просмотр событий на этапе трансформации
vector tap <transform_name>

# Режим отладки VRL в REPL
vector vrl --expression 'parse_json!(.message)'

# Просмотр логов Vector для диагностики ошибок VRL
journalctl -u vector -f | grep -i "vrl\|remap\|parse_error"
```

### Частые проблемы

**1. События отбрасываются с `dropped`**

Причины:
*   Fallible-функция вызвана без `!` или обработки ошибки.
*   `abort` в коде.
*   Превышен лимит памяти на событие.

Диагноз: настройте `reroute_dropped` в `remap` transform, чтобы отброшенные события отправлялись в отдельный sink для анализа.

**2. Медленный парсинг**

Причины:
*   Сложные regex в `parse_grok` или `parse_regex`.
*   Большие массивы в `for_each`.

Диагноз: проверьте `component_latency_seconds` для transform. Замените regex на специализированный парсер (`parse_json`, `parse_syslog`).

**3. Потеря полей после `merge`**

Причина: `merge` по умолчанию поверхностный (shallow). Вложенные объекты перезаписываются целиком.

Решение: используйте `merge(deep: true)` для глубокого объединения.

**4. `find` возвращает `null` вместо `-1` (v0.55+)**

Старый код:
```vrl
idx = find(.tags, "error")
if idx < 0 { ... }  # Устарело: find возвращает null
```

Новый код:
```vrl
idx = find(.tags, "error")
if idx == null { ... }
```

### Best Practices

1.  **Обрабатывайте все fallible-функции.** Даже если вы «уверены» в формате данных, добавляйте `!` или кортежную обработку. Это убережёт от падения Vector при изменении формата логов.
2.  **Выносите длинные программы во внешние файлы.** Используйте `file: "/etc/vector/transforms/parse.vrl"`. Это упрощает версионность и тестирование.
3.  **Тестируйте перед деплоем.** Используйте `vector test` с секцией `[[tests]]` для каждой трансформации.
4.  **Избегайте `http_request` в hot path.** Сетевые вызовы на каждое событие снижают производительность на порядок. Используйте `enrichment_tables` для статических данных.
5.  **Не используйте VRL для сложной агрегации.** Для оконных функций, группировки и дедупликации используйте `aggregate` transform, а не циклы в VRL.
6.  **Нормализуйте timestamp как можно раньше.** Многие парсеры (например, `parse_syslog`) возвращают время без года; приводите его к UTC сразу после парсинга.
7.  **Используйте `exists()` перед доступом к опциональным полям.** Это исключает `null` и делает код чище.
8.  **Логируйте ошибки обогащения.** Если `get_enrichment_table_record` не нашёл запись, это не всегда ошибка. Используйте `log()` с уровнем `warn` или `debug`.

### Валидация и тестирование

**Валидация конфигурации:**
```bash
vector validate /etc/vector/vector.yaml
# → Config is valid
```

**Интерактивная проверка VRL:**
```bash
vector vrl
> parse_syslog!("<13>1 2026-01-15T10:00:00Z web-01 sshd 1234 - - Accepted publickey for admin from 192.168.1.1")
```

**Unit-тесты в конфигурации:**
```toml
[[tests]]
  name = "auth_log_parsing"
  [tests.input]
    insert_at = "normalize_auth"
    type = "raw"
    value = 'Jan 15 10:23:45 web-01 sshd[1234]: Accepted publickey for admin from 192.168.1.10 port 22 ssh2'
  [[tests.outputs]]
    extract_from = "normalize_auth"
    [[tests.outputs.conditions]]
      type = "vrl"
      source = '''
        .event_type == "ssh_success"
        && .source_ip == "192.168.1.10"
        && .user == "admin"
      '''
```

Запуск тестов:
```bash
vector test /etc/vector/vector.yaml
# → 1 test(s) passed
```

### Ограничения и крайние случаи

*   **Нет циклов:** если вы пытаетесь реализовать рекурсивный обход без ограничения глубины — это приведёт к падению по лимиту стека. Используйте `map_keys(recursive: true)` для рекурсии.
*   **Нет пользовательских функций:** общая логика, повторяющаяся в нескольких программах, должна быть вынесена в шаблоны (например, через `include` в `source` или внешний файл).
*   **`parse_grok` требует точных паттернов.** Неверный паттерн приведёт к тихому отбрасыванию событий. Всегда проверяйте на реальных данных через `vector vrl`.
*   **`random_float()` не детерминирован.** Для воспроизводимых тестов используйте фиксированный сид или мокайте значение.
*   **`now()` возвращает время Vector, а не время события.** Для корреляции используйте поле `@timestamp` или парсите время из сырого лога.
*   **`http_request` блокирует обработку.** Используйте только в `remap` с низким throughput или в режиме агрегатора с достаточным количеством реплик.

---

## Применение VRL в Vector (DevOps/SRE)

### Внешние VRL-файлы и live-перезагрузка

*   `file: "/paths/program.vrl"` в `remap` — вынести программу во внешний файл.
*   `--watch-config` — слежение за изменениями внешних VRL-файлов.
*   `SIGHUP` — перезагрузка внешних VRL-файлов без рестарта (начиная с 2026 г.).

### Мониторинг качества трансформаций

При работе с VRL в production отслеживайте:

| Метрика Vector | Что означает | Действие |
| :--- | :--- | :--- |
| `component_errors_total{component_type="transform"}` | Ошибки в VRL (fallible без обработки, parse errors) | Настройте алерт на рост >0 |
| `component_received_events_total` / `component_sent_events_total` | Дисбаланс = отброшенные события | Проверьте `drop_on_error` и `abort` |
| `component_latency_seconds` | Время выполнения VRL на одно событие | Если >10ms — оптимизируйте парсеры |
| `dropped_events_total` | Количество отброшенных событий | Проверьте логи Vector |

---

## Дополнительная информация

### Инструменты разработки

*   **`vector vrl`** — встроенный интерактивный REPL (начиная с v0.56 содержит полный набор функций, включая Vector-специфичные).
*   **VRL Playground ([vrl.dev](https://vrl.dev))** — онлайн-отладчик скриптов (с 2026 добавлен селектор таймзоны и замер производительности).
*   **Unit-тестирование:** секция `[[tests]]` в конфигурации, сценарии input → output; VRL-условия включая `assert`/`assert_eq`, проверка количества событий через `expected_event_count`.

### См. также

*   [Vector Overview](./vector_overview.md) — общая архитектура Vector.
*   [Practical Scenarios](./practical_scenarios.md) — применение VRL в пайплайнах Kafka и OpenSearch.
*   [Official VRL documentation](https://vector.dev/docs/reference/vrl/) — полный справочник функций и синтаксиса.
