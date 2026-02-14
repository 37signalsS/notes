# Конфигурация Fluent Bit

## Определения

**Секция `[SERVICE]`** — глобальные настройки демона Fluent Bit.

**Секция `[INPUT]`** — конфигурация источников сбора логов.

**Секция `[FILTER]`** — правила модификации и обогащения логов.

**Секция `[OUTPUT]`** — конфигурация назначений для отправки логов.

**Parsers File** — внешний файл с определениями парсеров.

## Основные концепции

### Жизненный цикл лога

```
[INPUT] → [PARSER] → [FILTER] → [OUTPUT]
   ↓          ↓          ↓          ↓
Сбор    →   Парсинг  →  Обработка → Отправка
```

### Секция `[SERVICE]`: Глобальные настройки

```yaml
config:
  service: |
    [SERVICE]
        Flush         1
        Daemon        Off
        Log_Level     info
        Parsers_File  parsers.conf
        HTTP_Server   On
        HTTP_Listen   0.0.0.0
        HTTP_Port     2020
        storage.path        /var/lib/fluent-bit/storage
        storage.sync        normal
        storage.backlog.mem_limit 128M
```

**Ключевые параметры:**

| Параметр | Описание |
|----------|----------|
| `Flush` | Интервал отправки логов в output (секунды) |
| `Daemon` | Режим работы (`Off` для контейнеров) |
| `Log_Level` | Уровень логирования (`error`, `warn`, `info`, `debug`, `trace`) |
| `Parsers_File` | Путь к файлу с парсерами |
| `HTTP_Server` | Включение HTTP API для метрик |
| `storage.*` | Настройки файловой буферизации |

### Секция `[INPUT]`: Сбор логов

**Плагин `tail`** — чтение логов из файлов:

```yaml
[INPUT]
    Name              tail
    Tag               kube.*
    Path              /var/log/containers/*.log
    Parser            docker
    Mem_Buf_Limit     10MB
    Skip_Long_Lines   On
    storage.type      filesystem
```

**Плагин `systemd`** — сбор из journald:

```yaml
[INPUT]
    Name              systemd
    Tag               host.*
    Systemd_Filter    _SYSTEMD_UNIT=kubelet.service
    Read_From_Tail    On
```

### Секция `[FILTER]`: Обработка логов

**Плагин `kubernetes`** — обогащение метаданными K8s:

```yaml
[FILTER]
    Name                kubernetes
    Match               kube.*
    Kube_URL            https://kubernetes.default.svc:443
    Merge_Log           On
    Keep_Log            Off
    K8S-Logging.Parser  On
    K8S-Logging.Exclude On
```

**Параметры:**
- `Merge_Log On` — поднятие JSON-полей на верхний уровень
- `Keep_Log Off` — удаление исходного поля `log` после парсинга
- `K8S-Logging.Parser On` — разрешение аннотаций для переопределения парсера

### Секция `[OUTPUT]`: Отправка логов

```yaml
[OUTPUT]
    Name               es
    Match              kube.*
    Host               elasticsearch-master.logging.svc.cluster.local
    Port               9200
    Logstash_Format    On
    Logstash_Prefix    kube
    Replace_Dots       On
    Retry_Limit        False
```

## Практические сценарии

### Сценарий 1: Базовая конфигурация для Kubernetes

```yaml
config:
  service: |
    [SERVICE]
        Flush        1
        Log_Level    info
        Parsers_File parsers.conf
  
  inputs: |
    [INPUT]
        Name  tail
        Tag   kube.*
        Path  /var/log/containers/*.log
        Parser docker
  
  filters: |
    [FILTER]
        Name     kubernetes
        Match    kube.*
        Merge_Log On
  
  outputs: |
    [OUTPUT]
        Name es
        Match kube.*
        Host elasticsearch.logging.svc
        Port 9200
```

### Сценарий 2: Production-ready конфигурация

```yaml
config:
  service: |
    [SERVICE]
        Flush         1
        Log_Level     warning
        HTTP_Server   On
        HTTP_Port     2020
        storage.path  /var/lib/fluent-bit/storage
        storage.sync  normal
  
  inputs: |
    [INPUT]
        Name         tail
        Tag          kube.*
        Path         /var/log/containers/*.log
        Parser       docker
        storage.type filesystem
        Mem_Buf_Limit 50MB
  
  filters: |
    [FILTER]
        Name                kubernetes
        Match               kube.*
        Merge_Log           On
        Keep_Log            Off
        K8S-Logging.Parser  On
  
  outputs: |
    [OUTPUT]
        Name            es
        Match           kube.*
        Host            elasticsearch-master.logging.svc
        Port            9200
        Logstash_Format On
        Replace_Dots    On
        Retry_Limit     False
```

### Сценарий 3: Множественные output

```yaml
config:
  outputs: |
    [OUTPUT]
        Name  es
        Match kube.*
        Host  es.logging.svc
        Port  9200
    
    [OUTPUT]
        Name  stdout
        Match *
        Format json
```

## Дополнительная информация

- Детали парсинга и форматы: [parsing.md](./parsing.md)
- Буферизация и надежность: [buffering_routing.md](./buffering_routing.md)
- Сравнение с Fluentd: [fluent_comparison.md](./fluent_comparison.md)
- Критерии выбора: [selection_criteria.md](./selection_criteria.md)

**Примечание**: Парсеры и форматы логов подробно описаны в [parsing.md](./parsing.md).
