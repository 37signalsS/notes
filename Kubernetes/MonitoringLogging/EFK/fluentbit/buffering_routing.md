# Буферизация и маршрутизация в Fluent Bit

## Определения

**Буферизация** — механизм временного хранения логов перед отправкой в назначение, обеспечивающий надежность доставки при сбоях сети или хранилища.

**Storage Layer** — подсистема Fluent Bit для дисковой буферизации логов.

**Тег (Tag)** — идентификатор потока логов, используемый для маршрутизации.

**Маршрутизация** — процесс определения, в какой output отправлять лог на основе его тега.

## Основные концепции

### Модели буферизации

Fluent Bit поддерживает два типа буферизации:

1. **Memory Buffer** — буферизация в оперативной памяти (по умолчанию)
2. **Filesystem Buffer** — буферизация на диске с резервированием в памяти

### Параметры буферизации

**Глобальные настройки** (`[SERVICE]`):

| Параметр | Описание |
|----------|----------|
| `storage.path` | Путь к директории для файлового буфера |
| `storage.sync` | Режим синхронизации (`normal`/`full`) |
| `storage.backlog.mem_limit` | Лимит памяти для backlog |

**Настройки входа** (`[INPUT]`):

| Параметр | Описание |
|----------|----------|
| `storage.type` | Тип буфера (`memory`/`filesystem`) |
| `Mem_Buf_Limit` | Лимит памяти для входного буфера |

### Механизм маршрутизации

Каждый `[OUTPUT]` использует:

- `Match` — точное совпадение тега (glob-шаблоны: `*`, `**`)
- `Match_Regex` — регулярное выражение для тега

Приоритет: первый подходящий output получает лог (если не используется `copy`)

## Практические сценарии

### Сценарий 1: Надежная доставка с дисковым буфером

Применение: защита от потери логов при недоступности Elasticsearch.

```yaml
config:
  service: |
    [SERVICE]
        Flush        1
        storage.path /var/lib/fluent-bit/storage
        storage.sync normal
        storage.backlog.mem_limit 128M
  
  inputs: |
    [INPUT]
        Name         tail
        Tag          kube.*
        Path         /var/log/containers/*.log
        Parser       docker
        storage.type filesystem
        Mem_Buf_Limit 10MB
  
  outputs: |
    [OUTPUT]
        Name        es
        Match       kube.*
        Host        elasticsearch-master.logging.svc.cluster.local
        Port        9200
        Retry_Limit False
```

**Ключевые моменты:**

- `storage.type filesystem` — сохраняет логи на диск при перезапуске
- `Retry_Limit False` — бесконечные попытки отправки
- `storage.backlog.mem_limit` — защита от OOM

### Сценарий 2: Маршрутизация по namespace

```yaml
config:
  outputs: |
    [OUTPUT]
        Name  es
        Match kube.*
        Host  elasticsearch.logging.svc
        Port  9200
    
    [OUTPUT]
        Name  s3
        Match kube.*
        bucket logs-archive
        region us-east-1
```

### Сценарий 3: Разделение production и development логов

```yaml
config:
  filters: |
    [FILTER]
        Name   modify
        Match  kube.*
        Add    environment ${K8S_NAMESPACE}
  
  outputs: |
    [OUTPUT]
        Name  es
        Match kube.*
        Host  es-prod.logging.svc
        Port  9200
        Match_Regex ^kube\.(prod|api).*
    
    [OUTPUT]
        Name  es
        Match kube.*
        Host  es-dev.logging.svc
        Port  9200
        Match_Regex ^kube\.(dev|test).*
```

## Дополнительная информация

- Сравнение с Fluentd см. в [fluent_comparison.md](./fluent_comparison.md)
- Детали парсинга: [parsing.md](./parsing.md)
- Полная конфигурация: [fluentbit_configuration.md](./fluentbit_configuration.md)
- Критерии выбора инструментов: [selection_criteria.md](./selection_criteria.md)

**Примечание**: Сравнение механизмов буферизации Fluent Bit и Fluentd приведено в [fluent_comparison.md](./fluent_comparison.md).
