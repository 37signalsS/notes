# Конфигурация Fluent Bit

<!--
Reliability: 10 (Официальная документация Fluent Bit)
Freshness: 10 (Актуально для версий 2.x/3.x)
-->

## Определения

**Секция `[SERVICE]`** — блок глобальных настроек движка Fluent Bit, определяющий интервалы сброса данных, уровни логирования и параметры дисковой буферизации по умолчанию.

**Секция `[INPUT]`** — блок конфигурации источников данных (плагинов ввода). Каждому входу присваивается тег (Tag) для дальнейшей маршрутизации.

**Секция `[FILTER]`** — правила модификации, обогащения или фильтрации записей, проходящих через конвейер обработки.

**Секция `[OUTPUT]`** — блок конфигурации назначений (плагинов вывода) для отправки обработанных данных в системы хранения или анализа.

**Parsers_File** — внешний файл (традиционно `parsers.conf`), содержащий определения парсеров для разбора различных форматов логов.

## Основные концепции

### Жизненный цикл записи

Каждая запись проходит через строго определенную последовательность этапов:

```
[INPUT] → [PARSER] → [FILTER] → [OUTPUT]
   ↓          ↓          ↓          ↓
  Сбор    →  Разбор  → Обработка → Отправка
```

### Секция `[SERVICE]`: Глобальные настройки

```ini
[SERVICE]
    # Основные параметры
    Flush         1
    Daemon        Off
    Log_Level     info
    Parsers_File  parsers.conf
    
    # HTTP (HyperText Transfer Protocol) сервер для мониторинга
    HTTP_Server   On
    HTTP_Listen   0.0.0.0
    HTTP_Port     2020
    
    # Настройки дисковой буферизации
    storage.path        /var/lib/fluent-bit/storage/
    storage.sync        normal
    storage.backlog.mem_limit 128M
```

**Ключевые параметры:**

| Параметр | Описание |
|:---|:---|
| `Flush` | Интервал принудительной отправки данных из буфера (в секундах). |
| `Daemon` | Запуск в фоновом режиме. В контейнерах всегда должен быть `Off`. |
| `Log_Level` | Уровень детализации логов самого Fluent Bit (`error`, `warn`, `info`, `debug`). |
| `Parsers_File` | Путь к файлу с определениями парсеров. |
| `HTTP_Server` | Включение встроенного веб-сервера для экспорта метрик в формате Prometheus. |
| `storage.*` | Глобальные настройки подсистемы хранения для дисковой буферизации. |

### Секция `[INPUT]`: Сбор данных

**Плагин `tail`** — основной инструмент для чтения текстовых файлов логов в Kubernetes. Подробности разбора строк приведены в [parsing.md](./parsing.md).

```ini
[INPUT]
    Name              tail
    Tag               kube.*
    Path              /var/log/containers/*.log
    Parser            cri
    Mem_Buf_Limit     10MB
    Skip_Long_Lines   On
    storage.type      filesystem
```

**Примечание:** Для современных кластеров Kubernetes, использующих `containerd` или `CRI-O`, необходимо использовать парсер `cri` (Container Runtime Interface).

**Плагин `systemd`** — используется для сбора логов системных служб из journald.

```ini
[INPUT]
    Name              systemd
    Tag               host.*
    Systemd_Filter    _SYSTEMD_UNIT=kubelet.service
    Read_From_Tail    On
```

### Секция `[FILTER]`: Трансформация и обогащение

**Плагин `kubernetes`** — обогащает записи метаданными из API (Application Programming Interface) Kubernetes.

```ini
[FILTER]
    Name                kubernetes
    Match               kube.*
    Kube_URL            https://kubernetes.default.svc:443
    Merge_Log           On
    Keep_Log            Off
    K8S-Logging.Parser  On
    K8S-Logging.Exclude On
```

**Основные параметры:**

- `Merge_Log On`: Распаковывает содержимое поля `log`, если оно является JSON (JavaScript Object Notation), на верхний уровень записи.
- `Keep_Log Off`: Удаляет исходное текстовое поле `log` после успешного парсинга.
- `K8S-Logging.Parser On`: Позволяет управлять парсингом на уровне подов через аннотации `fluentbit.io/parser`.

### Секция `[OUTPUT]`: Доставка данных

```ini
[OUTPUT]
    Name               es
    Match              kube.*
    Host               elasticsearch-master.logging.svc.cluster.local
    Port               9200
    Logstash_Format    On
    Logstash_Prefix    my-cluster
    Replace_Dots       On
    Retry_Limit        False
```

**Основные параметры:**

- `Logstash_Format On`: Генерирует имена индексов в формате `logstash-YYYY.MM.DD`.
- `Replace_Dots On`: Заменяет точки в именах полей на подчеркивания для корректной работы маппинга в Elasticsearch.
- `Retry_Limit False`: Устанавливает бесконечное количество попыток переотправки при сбоях.

Детали механизмов надежности описаны в [buffering_routing.md](./buffering_routing.md).

## Практические сценарии

### Сценарий 1: Минимальная конфигурация для Kubernetes

Пример базового набора настроек для сбора логов и отправки в Elasticsearch.

```yaml
# fluent-bit-configmap.yaml
config:
  service: |
    [SERVICE]
        Flush        5
        Log_Level    info
        Parsers_File parsers.conf
  inputs: |
    [INPUT]
        Name   tail
        Tag    kube.*
        Path   /var/log/containers/*.log
        Parser cri
  filters: |
    [FILTER]
        Name      kubernetes
        Match     kube.*
        Merge_Log On
  outputs: |
    [OUTPUT]
        Name  es
        Match kube.*
        Host  elasticsearch.logging.svc
        Port  9200
```

### Сценарий 2: Конфигурация для высоконагруженных сред (Production)

Настройка с упором на надежность и мониторинг.

```yaml
# fluent-bit-configmap.yaml
config:
  service: |
    [SERVICE]
        Flush                5
        Log_Level            warning
        HTTP_Server          On
        HTTP_Port            2020
        storage.path         /var/lib/fluent-bit/storage/
        storage.sync         normal
        storage.checksum     On
  inputs: |
    [INPUT]
        Name            tail
        Tag             kube.*
        Path            /var/log/containers/*.log
        Parser          cri
        storage.type    filesystem
        Mem_Buf_Limit   50MB
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
        Match           *
        Host            elasticsearch-master.logging.svc
        Port            9200
        Logstash_Format On
        Replace_Dots    On
        Retry_Limit     False
```

## Дополнительная информация

- [Парсинг логов в Fluent Bit](./parsing.md) — детальное описание работы с парсерами и регулярными выражениями.
- [Буферизация и маршрутизация во Fluent Bit](./buffering_routing.md) — механизмы обеспечения надежности и управления потоками данных.
- [Сравнение Fluent Bit и Fluentd](./fluent_comparison.md) — критерии выбора между агентом и агрегатором.
