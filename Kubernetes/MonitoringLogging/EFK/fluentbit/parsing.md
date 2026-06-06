# Парсинг логов в Fluent Bit

<!--
Reliability: 10 (Официальная документация Fluent Bit)
Freshness: 10 (Базовый функционал, актуален для версий 2.x/3.x)
-->

## Определения

**Парсинг (Parsing)** — процесс преобразования неструктурированной строки лога в структурированную запись (набор пар ключ-значение).

**Парсер (Parser)** — именованный набор правил в конфигурации (`[PARSER]`), определяющий, как разбирать конкретный формат лога.

**Многострочный парсер (Multiline Parser)** — специальный тип парсера для объединения логов, которые занимают несколько строк (например, стектрейсы Java или Python).

**Ключ времени (Time_Key)** — поле в структурированной записи, которое содержит временную метку события.

**Формат времени (Time_Format)** — формат, используемый для разбора значения из `Time_Key`.

## Основные концепции

### Типы парсеров

| Формат | Тип парсера | Основное применение |
|:---|:---|:---|
| **CRI (Container Runtime Interface)** | `cri` или `regex` | Стандарт для Kubernetes. Логи от `containerd` и `CRI-O`. |
| **JSON (JavaScript Object Notation)** | `json` | Любые структурированные логи в формате JSON. |
| **Docker** | `docker` | Устаревший стандарт. Логи от Docker Engine в формате JSON. |
| **Regex** | `regex` | Произвольные текстовые форматы (nginx, syslog и т.д.). |
| **LTSV** | `ltsv` | Labeled Tab-separated Values. |
| **Syslog** | `syslog` | Системные логи (RFC3164/RFC5424). |

### Места применения парсинга

1. **На входе (`[INPUT]`)**: с помощью параметра `Parser`. Самый распространенный способ.
2. **В фильтре (`[FILTER]`)**: с помощью плагина `parser` для разбора поля внутри уже собранного лога.
3. **Динамически (через аннотации)**: Kubernetes-фильтр может применять парсеры на основе аннотации пода (`fluentbit.io/parser: "my-parser"`).

### Структура парсера

Определения парсеров обычно выносятся в отдельный файл (например, `parsers.conf`).

```ini
[PARSER]
    Name        <имя_парсера>
    Format      <тип_парсера> # regex, json, cri, и т.д.
    # Для regex
    Regex       <регулярное_выражение>
    # Для всех
    Time_Key    <поле_с_временем>
    Time_Format <формат_времени_в_strptime>
```

### Многострочный парсинг

Объединяет строки, принадлежащие одному событию, в единую запись. Используется для приложений со стектрейсами (Java, Python).

```ini
[MULTILINE_PARSER]
    Name          <имя>
    Type          regex
    Flush_Timeout <мс_до_сброса>
    # Правило: "состояние" "регулярное выражение" "новое_состояние"
    Rule          "start_state" "/^Начало нового лога/" "cont"
    Rule          "cont"        "/^НЕ начало нового лога/"  "cont"
```

## Практические сценарии

### Сценарий 1: Парсинг логов Kubernetes (CRI)

Разбор логов в современных кластерах (с `containerd` или `CRI-O`).

```ini
# parsers.conf
[PARSER]
    Name        cri
    Format      regex
    Regex       ^(?<time>[^ ]+) (?<stream>stdout|stderr) (?<logtag>[^ ]*) (?<log>.*)$
    Time_Key    time
    Time_Format %Y-%m-%dT%H:%M:%S.%L%z

# fluent-bit.conf
[INPUT]
    Name   tail
    Path   /var/log/containers/*.log
    Tag    kube.*
    Parser cri
```

### Сценарий 2: Парсинг JSON-логов

Сбор логов от приложения в формате JSON.

```ini
# parsers.conf
[PARSER]
    Name        app_json
    Format      json
    Time_Key    timestamp
    Time_Format %Y-%m-%dT%H:%M:%S.%L

# В поде приложения (аннотация):
# metadata:
#   annotations:
#     fluentbit.io/parser: "app_json"
```

### Сценарий 3: Многострочные Java-стектрейсы

Объединение стектрейсов Java в одно событие.

```ini
# parsers.conf
[MULTILINE_PARSER]
    Name          java_stack
    Type          regex
    Flush_Timeout 5000
    Rule "start_state" "/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}/" "cont"
    Rule "cont" "/^\s+at\s+|^\s*Caused by:/" "cont"

# fluent-bit.conf
[INPUT]
    Name             tail
    Path             /var/log/containers/my-java-app*.log
    Tag              my-java-app.*
    Multiline        On
    Multiline.Parser java_stack
```

## Дополнительная информация

* [Конфигурация Fluent Bit](./fluentbit_configuration.md) — общая структура конфигурационных файлов.
* [Буферизация и маршрутизация](./buffering_routing.md) — детали обработки данных после парсинга.
* [Сравнение Fluent Bit и Fluentd](./fluent_comparison.md) — выбор инструмента для сбора логов.
