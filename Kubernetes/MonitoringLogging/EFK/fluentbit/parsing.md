# Парсинг логов в Fluent Bit

Парсинг — это преобразование сырой строки лога в структурированную запись с полями и корректным временем события.

## Типы плагинов и место парсинга

- **Входные плагины:** `tail`, `systemd`, `tcp`, `forward`
- **Парсеры:** Секции `[PARSER]` и `[MULTILINE_PARSER]`

## Распространённые форматы и парсеры

| Формат | Fluent Bit (Parser) | Примечание |
| :--- | :--- | :--- |
| **JSON** | `json` | Быстрый и надёжный |
| **Docker (JSON file)** | `docker` | Ключ `log` содержит строку приложения |
| **CRI (K8s containerd)** | `cri` | Раскладывает `ts/stream/log` |
| **Регулярные выражения** | `regex` | Гибкость для произвольных форматов |
| **LTSV** | `ltsv` | Лог с `key:value` парами |
| **CSV** | `csv` | Требует определения колонок |
| **Syslog** | `syslog` | Может идти как input и как parse |

## Пример: парсинг CRI и многострочных стектрейсов Java

```yaml
config:
  customParsers: |
    [PARSER]
        Name        docker
        Format      json
        Time_Key    time
        Time_Format %Y-%m-%dT%H:%M:%S.%L
    
    [PARSER]
        Name        cri
        Format      regex
        Regex       ^(?<time>[^ ]+) (?<stream>stdout|stderr) (?<logtag>[^ ]*) (?<log>.*)$
        Time_Key    time
        Time_Format %Y-%m-%dT%H:%M:%S.%L%z

    [MULTILINE_PARSER]
        Name          java_stack
        Type          regex
        Flush_Timeout 5000
        Rule          "start_state"   "/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}.\d+Z/."  "cont"
        Rule          "cont"          "/^\s+at\s+|^\s*Caused by:/."                   "cont"

  inputs: |
    [INPUT]
        Name                tail
        Path                /var/log/containers/*.log
        Tag                 kube.*
        Parser              cri
        Multiline           On
        Multiline.Parser    java_stack
```

Здесь `Parser cri` разбирает стандартный формат логов CRI, а `Multiline.Parser java_stack` "склеивает" строки, относящиеся к одному Java-исключению.

## Практические ориентиры

- Предпочтителен изначально структурированный лог (JSON, LTSV)
- Указывайте `time_key` и `time_format`
- Включайте объединение многострочных записей для стектрейсов
- Сохраняйте часть «сырого» сообщения в отдельном поле для отладки
- Нормализуйте ключи и уровни логирования
- Избегайте чрезмерно сложных регулярных выражений на горячих путях
