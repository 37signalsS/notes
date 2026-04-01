# Парсинг логов в Fluent Bit

## Определения

**Парсинг (Parsing)** — процесс преобразования неструктурированной строки лога в структурированную запись (набор пар ключ-значение).

**Парсер (Parser)** — именованный набор правил в конфигурации (`[PARSER]`), определяющий, как разбирать конкретный формат лога.

**Многострочный парсер (Multiline Parser)** — специальный тип парсера для объединения логов, которые занимают несколько строк (например, стектрейсы Java или Python).

**Ключ времени (Time_Key)** — поле в структурированной записи, которое содержит временную метку события.

**Формат времени (Time_Format)** — формат, используемый для разбора значения из `Time_Key`.

## Основные концепции

### Типы парсеров

| Формат | Тип парсера | Основное применение |
|---|---|---|
| **CRI** | `cri` или `regex` | **Стандарт для Kubernetes.** Логи от `containerd` и `CRI-O`. |
| **JSON** | `json` | Любые структурированные логи в формате JSON. |
| **Docker** | `docker` | Легаси. Логи от Docker Engine в формате JSON. |
| Regex | `regex` | Произвольные текстовые форматы (nginx, syslog и т.д.). |
| LTSV | `ltsv` | Labeled Tab-separated Values. |
| Syslog | `syslog` | Системные логи (RFC3164/RFC5424). |

### Где применяется парсинг

1. **На входе (`[INPUT]`)**: с помощью параметра `Parser`. Самый распространенный способ.
2. **В фильтре (`[FILTER]`)**: с помощью плагина `parser` для разбора поля внутри уже собранного лога.
3. **Динамически (через аннотации)**: Kubernetes-фильтр может применять парсеры на основе аннотации пода (`fluentbit.io/parser: "my-parser"`).

Детали конфигурации Fluent Bit описаны в [fluentbit_configuration.md](./fluentbit_configuration.md).

### Структура парсера

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

Объединяет строки, принадлежащие одному событию, в единую запись. Используйте для приложений со стектрейсами (Java, Python), чтобы избежать разрозненных и нечитаемых ошибок.

```ini
[MULTILINE_PARSER]
    Name          <имя>
    Type          regex
    Flush_Timeout <мс_до_сброса>
    # Правило: "состояние" "регулярное выражение" "новое_состояние"
    Rule          "start_state" "/^Начало нового лога/." "cont"
    Rule          "cont"        "/^НЕ начало нового лога/."  "cont"
```

Избегайте сложных и неэффективных регулярных выражений на высоконагруженных системах. Детали буферизации описаны в [buffering_routing.md](./buffering_routing.md).

## Практические сценарии

### Сценарий 1: Парсинг логов Kubernetes (CRI)

**Задача:** Правильно разбирать логи в современном кластере Kubernetes, где средой выполнения является `containerd` или `CRI-O`.

```yaml
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

Это **рекомендуемый** подход для большинства современных инсталляций Kubernetes.

### Сценарий 2: Парсинг JSON-логов

**Задача:** Собирать логи от приложения, которое пишет их в формате JSON. Предпочитайте структурированные логи (JSON) везде, где это возможно — это упрощает парсинг и снижает нагрузку.

```yaml
# parsers.conf
[PARSER]
    Name        app_json
    Format      json
    Time_Key    timestamp # Поле в JSON, содержащее время
    Time_Format %Y-%m-%dT%H:%M:%S.%L

# fluent-bit.conf (с использованием аннотаций)
# В самом поде приложения:
# metadata:
#   annotations:
#     fluentbit.io/parser: "app_json"
```

Всегда указывайте `Time_Key` и `Time_Format`, чтобы время события корректно обрабатывалось в конечных системах.

### Сценарий 3: Многострочные Java-стектрейсы

**Задача:** Объединять многострочные стектрейсы Java в одно событие.

```yaml
# parsers.conf
[MULTILINE_PARSER]
    Name          java_stack
    Type          regex
    Flush_Timeout 5000
    # Начинаем новую запись, если строка начинается с даты
    Rule "start_state" "/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}/" "cont"
    # Продолжаем, если строка начинается с пробела (at, Caused by)
    Rule "cont" "/^\s+at\s+|^\s*Caused by:/" "cont"

# fluent-bit.conf
[INPUT]
    Name             tail
    Path             /var/log/containers/my-java-app*.log
    Tag              my-java-app.*
    # Включаем многострочный режим и указываем парсер
    Multiline        On
    Multiline.Parser java_stack
```

### Сценарий 4 (Легаси): Парсинг Docker-логов

**Задача:** Сбор логов в старых системах, использующих Docker Engine как среду выполнения Kubernetes.

```yaml
# parsers.conf
[PARSER]
    Name        docker
    Format      json
    Time_Key    time
    Time_Format %Y-%m-%dT%H:%M:%S.%L

# fluent-bit.conf
[INPUT]
    Name   tail
    Path   /var/log/containers/*.log
    Tag    kube.*
    Parser docker
```

Полная конфигурация Fluent Bit описана в [fluentbit_configuration.md](./fluentbit_configuration.md). Сравнение с Fluentd для выбора архитектуры — в [fluent_comparison.md](./fluent_comparison.md).
