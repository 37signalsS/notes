# Парсинг логов в Fluent Bit

## Определения

**Парсинг** — преобразование сырой строки лога в структурированную запись с полями.

**Парсер (Parser)** — конфигурационная секция `[PARSER]`, определяющая правила разбора формата.

**Multiline Parser** — парсер для объединения многострочных записей (например, стектрейсов).

**Time Key** — поле, содержащее timestamp события.

**Time Format** — формат даты/времени для парсинга timestamp.

## Основные концепции

### Типы парсеров

| Формат | Тип Parser | Применение |
|--------|-----------|------------|
| JSON | `json` | Структурированные логи |
| Docker | `docker` | Логи контейнеров Docker |
| CRI | `cri` или `regex` | Логи containerd/CRI-O |
| Regex | `regex` | Произвольные форматы |
| LTSV | `ltsv` | Labelled Tab-separated Values |
| CSV | `csv` | Табличные данные |
| Syslog | `syslog` | Системные логи RFC3164/RFC5424 |

### Где применяется парсинг

1. **На входе** (`[INPUT]`): параметр `Parser`
2. **В фильтре** (`[FILTER]`): плагин `parser`
3. **Автоматически**: через аннотации Kubernetes (`K8S-Logging.Parser`)

### Структура парсера

```ini
[PARSER]
    Name        <имя>
    Format      <тип>
    Time_Key    <поле_времени>
    Time_Format <формат_времени>
```

### Multiline парсинг

Используется для объединения связанных строк:

```ini
[MULTILINE_PARSER]
    Name          <имя>
    Type          regex
    Flush_Timeout <мс>
    Rule          "<состояние>" "<регекс>" "<след_состояние>"
```

## Практические сценарии

### Сценарий 1: Парсинг Docker-логов

```yaml
config:
  customParsers: |
    [PARSER]
        Name        docker
        Format      json
        Time_Key    time
        Time_Format %Y-%m-%dT%H:%M:%S.%L
  
  inputs: |
    [INPUT]
        Name   tail
        Path   /var/log/containers/*.log
        Tag    kube.*
        Parser docker
```

### Сценарий 2: Парсинг CRI-формата (containerd)

```yaml
config:
  customParsers: |
    [PARSER]
        Name        cri
        Format      regex
        Regex       ^(?<time>[^ ]+) (?<stream>stdout|stderr) (?<logtag>[^ ]*) (?<log>.*)$
        Time_Key    time
        Time_Format %Y-%m-%dT%H:%M:%S.%L%z
  
  inputs: |
    [INPUT]
        Name   tail
        Path   /var/log/containers/*.log
        Tag    kube.*
        Parser cri
```

### Сценарий 3: Многострочные Java-стектрейсы

```yaml
config:
  customParsers: |
    [MULTILINE_PARSER]
        Name          java_stack
        Type          regex
        Flush_Timeout 5000
        Rule          "start_state"   "/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}.\d+Z/."  "cont"
        Rule          "cont"          "/^\s+at\s+|^\s*Caused by:/."                   "cont"
  
  inputs: |
    [INPUT]
        Name             tail
        Path             /var/log/containers/*.log
        Tag              kube.*
        Multiline        On
        Multiline.Parser java_stack
```

**Логика работы:**

- `start_state` — начало новой записи (timestamp)
- `cont` — продолжение предыдущей записи (строки `at` или `Caused by`)
- `Flush_Timeout` — принудительная отправка через 5 секунд

### Сценарий 4: Парсинг через фильтр

```yaml
config:
  inputs: |
    [INPUT]
        Name tcp
        Port 5170
        Tag  app.*
  
  filters: |
    [FILTER]
        Name   parser
        Match  app.*
        Parser json
        Key_Name log
        Reserve_Data On
```

### Сценарий 5: Пользовательский формат логов

```yaml
config:
  customParsers: |
    [PARSER]
        Name        myapp
        Format      regex
        Regex       ^\[(?<level>\w+)\] (?<time>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) - (?<message>.*)$
        Time_Key    time
        Time_Format %Y-%m-%d %H:%M:%S
  
  inputs: |
    [INPUT]
        Name   tail
        Path   /var/log/myapp/*.log
        Tag    app.myapp
        Parser myapp
```

## Дополнительная информация

- Конфигурация Fluent Bit: [fluentbit_configuration.md](./fluentbit_configuration.md)
- Буферизация и маршрутизация: [buffering_routing.md](./buffering_routing.md)
- Сравнение с Fluentd: [fluent_comparison.md](./fluent_comparison.md)
- Критерии выбора: [selection_criteria.md](./selection_criteria.md)

**Рекомендации:**

- Предпочитайте изначально структурированные логи (JSON)
- Всегда указывайте `Time_Key` и `Time_Format`
- Включайте `Multiline` для приложений со стектрейсами
- Сохраняйте сырые сообщения при отладке
- Нормализуйте уровни логирования
- Избегайте сложных регулярных выражений на высоких нагрузках
