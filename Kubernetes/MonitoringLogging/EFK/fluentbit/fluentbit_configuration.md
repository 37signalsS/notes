# Конфигурация Fluent Bit

## Определения

**Секция `[SERVICE]`** — глобальные настройки движка Fluent Bit: интервалы, уровни логирования, настройки буферизации по умолчанию.

**Секция `[INPUT]`** — конфигурация источников данных (например, чтение файлов или прием по сети). Каждому входу присваивается тег.

**Секция `[FILTER]`** — правила модификации, обогащения или фильтрации логов, проходящих через конвейер.

**Секция `[OUTPUT]`** — конфигурация назначений для отправки обработанных логов (например, Elasticsearch или Kafka).

**Parsers File** — внешний файл (`parsers.conf`) с определениями пользовательских парсеров.

## Основные концепции

### Жизненный цикл лога

Лог проходит через последовательность шагов, образующих конвейер:

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
    
    # HTTP-сервер для мониторинга (Prometheus метрики)
    HTTP_Server   On
    HTTP_Listen   0.0.0.0
    HTTP_Port     2020
    
    # Настройки дисковой буферизации по умолчанию
    storage.path        /var/lib/fluent-bit/storage/
    storage.sync        normal
    storage.backlog.mem_limit 128M
```

**Ключевые параметры:**

| Параметр | Описание |
|----------|----------|
| `Flush` | Интервал принудительной отправки данных из буфера (секунды). |
| `Daemon` | Запуск в фоновом режиме. Для контейнеров всегда `Off`. |
| `Log_Level` | Уровень логирования самого Fluent Bit (`error`, `warn`, `info`, `debug`). |
| `Parsers_File` | Путь к файлу с парсерами. |
| `HTTP_Server` | Включение встроенного HTTP-сервера для метрик и API. |
| `storage.*` | Глобальные настройки дисковой буферизации. |

### Секция `[INPUT]`: Сбор логов

**Плагин `tail`** — чтение логов из файлов. Основной плагин для Kubernetes. Детали парсинга описаны в [parsing.md](./parsing.md).

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

**Примечание:** Для современных кластеров Kubernetes (использующих `containerd` или `CRI-O`) следует использовать парсер `cri`. Парсер `docker` актуален для старых систем на Docker Engine.

**Плагин `systemd`** — сбор логов системных служб из journald.

```ini
[INPUT]
    Name              systemd
    Tag               host.*
    Systemd_Filter    _SYSTEMD_UNIT=kubelet.service
    Read_From_Tail    On
```

### Секция `[FILTER]`: Обработка логов

**Плагин `kubernetes`** — обогащение логов метаданными из K8s API.

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

**Ключевые параметры:**

- `Kube_URL`: Адрес API-сервера. **Примечание:** Обычно Fluent Bit автоматически обнаруживает его, когда запущен в поде.
- `Merge_Log On`: "Поднимает" поля из JSON-строки лога на верхний уровень записи.
- `Keep_Log Off`: Удаляет исходное поле `log` после успешного парсинга и слияния.
- `K8S-Logging.Parser On`: Разрешает подам через аннотации (`fluentbit.io/parser`) указывать, какой парсер применять к их логам.

### Секция `[OUTPUT]`: Отправка логов

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

**Ключевые параметры:**

- `Logstash_Format On`: Создает индексы в формате `logstash-YYYY.MM.DD`.
- `Replace_Dots On`: Заменяет точки в именах полей на подчеркивания, чтобы избежать конфликтов маппинга в Elasticsearch.
- `Retry_Limit False`: Включает бесконечные попытки переотправки.

Детали буферизации и маршрутизации описаны в [buffering_routing.md](./buffering_routing.md).

## Практические сценарии

### Сценарий 1: Базовая конфигурация для Kubernetes

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

### Сценарий 2: Production-ready конфигурация

```yaml
# fluent-bit-configmap.yaml
config:
  service: |
    [SERVICE]
        Flush                5
        Log_Level            warning # Снижаем уровень логирования для прода
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
        storage.type    filesystem # Включаем дисковую буферизацию
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
        Match           * # Принимаем все логи
        Host            elasticsearch-master.logging.svc
        Port            9200
        Logstash_Format On
        Replace_Dots    On
        Retry_Limit     False
```

Сравнение с Fluentd и выбор архитектуры описаны в [fluent_comparison.md](./fluent_comparison.md).
