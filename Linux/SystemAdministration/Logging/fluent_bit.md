# Fluent Bit: Сбор и пересылка логов

## Определения

**Fluent Bit** — легковесный, высокопроизводительный агент сбора и пересылки логов, написанный на C. Является стандартом де-факто для сбора логов в Kubernetes (DaemonSet), но также широко используется на bare-metal серверах и в systemd-средах. Потребление RAM: ~20 МБ, что делает его идеальным для ресурсно-ограниченных сред.

**Позиция в стеке:** Fluent Bit — это collector (агент сбора), расположенный на каждом хосте. Он читает логи из различных источников (файлы, journald, syslog, stdin) и отправляет их в хранилище (Elasticsearch, Loki, Kafka, S3) или промежуточный агрегатор (Fluentd, Vector).

```
[Источники] → [Fluent Bit (Input → Filter → Output)] → [Хранилище]
```

## Базовые концепции

### Архитектура pipeline

Fluent Bit обрабатывает данные через три этапа:

```
Input (чтение) → Filter (обработка) → Output (отправка)
```

| Этап | Модули | Назначение |
|:---|:---|:---|
| **Input** | `tail`, `systemd`, `syslog`, `exec`, `net`, `random` | Чтение данных из источника |
| **Filter** | `grep`, `record_modifier`, `parser`, `modify`, `nest`, `lua` | Трансформация и фильтрация |
| **Output** | `es`, `opensearch`, `loki`, `kafka`, `s3`, `http`, `file`, `null` | Отправка в хранилище |

### Конфигурация

**Основные файлы:**

| Файл | Описание |
|:---|:---|
| `/etc/fluent-bit/fluent-bit.conf` | Главный конфигурационный файл |
| `/etc/fluent-bit/parsers.conf` | Определения парсеров |
| `/etc/fluent-bit/custom_parsers.conf` | Пользовательские парсеры |
| `/var/lib/fluent-bit/flb_kube.db` | База состояния (checkpoint) |

**Синтаксис (INI-like):**

```ini
[SERVICE]
    Flush           5
    Log_Level       info
    Daemon          off
    Parsers_File    parsers.conf
    HTTP_Server     On
    HTTP_Listen     0.0.0.0
    HTTP_Port       2020
    storage.path    /var/lib/fluent-bit/state/
    storage.sync    normal
    storage.checksum off
    storage.backlock off

[INPUT]
    Name            tail
    Tag             app.*
    Path            /var/log/app/*.log
    Parser          json
    DB              /var/lib/fluent-bit/state/flb_kube.db
    Mem_Buf_Limit   50MB
    Skip_Long_Lines On
    Refresh_Interval 10

[FILTER]
    Name            grep
    Match           app.*
    Regex           level ^(ERROR|CRITICAL)$

[OUTPUT]
    Name            loki
    Match           app.*
    Host            loki.internal
    Port            3100
    Labels          job=app, env=production
    Label_Keys      $service
    Remove_Keys     secret_field
    Line_Format     json
```

## Практические сценарии

### Сценарий 1: Сбор системных логов (journald → Loki)

```ini
# /etc/fluent-bit/fluent-bit.conf

[SERVICE]
    Flush           5
    Log_Level       warning
    Daemon          off
    Parsers_File    parsers.conf
    HTTP_Server     On
    HTTP_Listen     0.0.0.0
    HTTP_Port       2020
    storage.path    /var/lib/fluent-bit/state/

[INPUT]
    Name            systemd
    Tag             host.*
    Strip_Underscores On
    Systemd_Filter  _SYSTEMD_UNIT=sshd.service
    Systemd_Filter  _SYSTEMD_UNIT=nginx.service
    Systemd_Filter  _SYSTEMD_UNIT=postgresql.service
    Read_From_Tail  On

[FILTER]
    Name            modify
    Match           host.*
    Add             host ${HOSTNAME}

[OUTPUT]
    Name            loki
    Match           host.*
    Host            loki.internal
    Port            3100
    Labels          job=system, env=production
    Label_Keys      $HOSTNAME
    Line_Format     json
    Retry_Limit     5
```

### Сценарий 2: Сбор логов приложений (tail → Elasticsearch)

```ini
# /etc/fluent-bit/fluent-bit.conf

[INPUT]
    Name            tail
    Tag             app.*
    Path            /var/log/nginx/access.log,/var/log/nginx/error.log
    multiline.parser docker, go
    Parser          nginx
    DB              /var/lib/fluent-bit/state/nginx.db
    Mem_Buf_Limit   100MB
    Skip_Long_Lines On
    Refresh_Interval 5
    Read_from_Head  false

[FILTER]
    Name            parser
    Match           app.*
    Key_Name        log
    Parser          nginx
    Reserve_Data    On
    Preserve_Key    On

[FILTER]
    Name            grep
    Match           app.*
    Exclude         status ^(200|301|302)$

[OUTPUT]
    Name            es
    Match           app.*
    Host            elasticsearch.internal
    Port            9200
    Index           nginx-access
    Type            _doc
    HTTP_User       elastic
    HTTP_Passwd     ${ES_PASSWORD}
    Logstash_Format On
    Logstash_Prefix nginx
    Logstash_DateFormat %Y.%m.%d
    Retry_Limit     5
    Replace_Dots    On
    Suppress_Type_Name On
```

### Сценарий 3: Парсинг nginx access log

```conf
# /etc/fluent-bit/parsers.conf

[PARSER]
    Name        nginx
    Format      regex
    Regex       ^(?<remote>[^ ]*) (?<host>[^ ]*) (?<user>[^ ]*) \[(?<time>[^\]]*)\] "(?<method>\S+)(?: +(?<path>[^\"]*?)(?: +\S*)?)?" (?<code>[^ ]*) (?<size>[^ ]*)(?: "(?<referer>[^\"]*)" "(?<ua>[^\"]*)")?$
    Time_Key    time
    Time_Format %d/%b/%Y:%H:%M:%S %z

[PARSER]
    Name        json
    Format      json
    Time_Key    timestamp
    Time_Format %Y-%m-%dT%H:%M:%S.%L%z

[PARSER]
    Name        syslog-rfc5424
    Format      regex
    Regex       ^\<(?<pri>[0-9]{1,5})\>(?<version>[0-9])? (?<timestamp>[^ ]+) (?<host>[^ ]+) (?<ident>[^ ]+)?(?:(?:\[?(?<pid>[0-9]+)?\]?))?(?: ?(?<msgid>[^ ]+))?(?: ?(?<extradata>[^\[]*))?\ ?:(?<message>.+)$
    Time_Key    timestamp
    Time_Format %Y-%m-%dT%H:%M:%S.%L%z
```

### Сценарий 4: Маскирование PII (фильтр)

```ini
[FILTER]
    Name          record_modifier
    Match         app.*
    Remove_key    password
    Remove_key    secret
    Remove_key    api_key
    Remove_key    token
    # Maskirovanie PAN
    Regex         card_number ^(\\d{4})\\d{8}(\\d{4})$ $1****$2
```

### Сценарий 5: Disk buffer для отказоустойчивости

```ini
[SERVICE]
    storage.path            /var/lib/fluent-bit/buffer/
    storage.sync            normal
    storage.checksum        off
    storage.backlog_size_limit 256M

[OUTPUT]
    Name            loki
    Match           *
    Host            loki.internal
    Port            3100
    storage.total_limit_size 500M
    storage.pause_on_chunks_overlimit On
    Retry_Limit     5
```

### Сценарий 6: Мониторинг самого Fluent Bit

```bash
# HTTP API (включен через HTTP_Server On)
# Проверка здоровья
curl -s http://localhost:2020/api/v1/health | jq .
# → {"status":"ok"}

# Метрики для Prometheus
curl -s http://localhost:2020/api/v1/metrics/prometheus

# Статус storage
curl -s http://localhost:2020/api/v1/storage | jq .

# Проверка flush
curl -s http://localhost:2020/api/v1/flushes | jq .

# Логи Fluent Bit
journalctl -u fluent-bit -f --no-pager | tail -20
```

**Ключевые метрики:**

| Метрика | Описание | Порог алерта |
|:---|:---|:---|
| `fluentbit_input_records_total` | Записей в секунду | Зависит от SLA |
| `fluentbit_output_errors_total` | Ошибки отправки | > 0 |
| `fluentbit_output_retries_total` | Повторные попытки | > 100/min |
| `fluentbit_process_resident_memory_bytes` | Потребление RAM | > 256MB |
| `fluentbit_storage_chunks_total` | Чанки в storage | > 1000 |

### Сценарий 7: Валидация конфигурации

```bash
# Синтаксическая проверка (dry run)
fluent-bit -c /etc/fluent-bit/fluent-bit.conf --dry-run

# Проверка парсеров
fluent-bit -L

# Запуск с отладочным выводом
fluent-bit -c /etc/fluent-bit/fluent-bit.conf -d

# Проверка конфигурации в Kubernetes
kubectl logs -n logging -l app=fluent-bit --tail=50 | grep -i error
```

## Диагностика и устранение неполадок

| Проблема | Причина | Решение |
|:---|:---|:---|
| **OOM-kill** | `Mem_Buf_Limit` слишком низкий | Увеличить `Mem_Buf_Limit`, добавить `storage.total_limit_size` |
| **Потеря логов** | Disk buffer не настроен | Добавить `storage.path` и `storage.total_limit_size` |
| **Логи не доставляются** | DNS, firewall, credentials | `curl -v http://loki:3100/loki/api/v1/push`, проверить сертификаты |
| **Дублирование логов** | Несколько конфигов с одним Match | Проверить `fluent-bit -c config --dry-run`, исключить дубли |
| **Высокое потребление RAM** | Большие `Mem_Buf_Limit` на многих INPUT | Уменьшить лимиты, включить disk buffer |
| **Сломанный парсинг** | Изменение формата лога | Проверить regex в parsers.conf через `fluent-bit -L` |
| **Старые логи не читаются** | `Read_from_Head false` | Установить `Read_from_Head true` для initial backfill |

## Дополнительная информация

### Сравнение агентов сбора

| Параметр | **Fluent Bit** | **Vector** | **Promtail** | **rsyslog** |
|:---|:---|:---|:---|:---|
| **Язык** | C | Rust | Go | C |
| **RAM** | ~20 МБ | ~50 МБ | ~100 МБ | <50 МБ |
| **Входы** | tail, systemd, syslog, net | journald, file, syslog, kafka | journal, file, kmsg | imjournal, imfile, imtcp |
| **Выходы** | es, loki, kafka, s3, http | loki, es, kafka, s3, datadog | loki | omfwd, omfile, omelasticsearch |
| **Kubernetes** | DaemonSet (стандарт) | DaemonSet | DaemonSet | Нет |
| **Фильтры** | grep, record_modifier, lua | VRL (мощный) | pipeline_stages | property-based |
| **Parallélisme** | Ограниченный | Многопоточный | Ограниченный | Ограниченный |

### Когда использовать Fluent Bit

- **Kubernetes** — стандарт для DaemonSet-сбора логов
- **Минимальный footprint** — 20 МБ RAM, ideal для edge и IoT
- **Простые pipeline** — Input → Filter → Output без сложной трансформации
- **Loki/Elasticsearch** — нативная поддержка обоих

### Когда выбирать Vector вместо Fluent Bit

- Сложные трансформации (VRL мощнее regex)
- Многопоточная обработка на высоконагруженных системах
- Единый агент для логов + метрик + трейсов

### Лучшие практики

1. **Используйте disk buffer** (`storage.path`) для production — защита от потери при недоступности бэкенда.
2. **Настройте `storage.total_limit_size`** — ограничьте объём буфера на диске.
3. **`storage.pause_on_chunks_overlimit On`** — приостановка чтения при переполнении буфера.
4. **Используйте `Skip_Long_Lines On`** — предотвращает блокировку на очень длинных строках.
5. **Включайте `HTTP_Server`** — для мониторинга через Prometheus.
6. **Настройте `Refresh_Interval`** — как часто Fluent Bit проверяет наличие новых строк в файлах.
7. **Используйте `DB`** — для checkpoint'ов, чтобы не перечитывать файлы с начала после перезапуска.
8. **Исключайте debug-логи** через фильтр `grep` в production.
9. **Тестируйте конфигурацию** через `--dry-run` перед деплоем.
10. **Мониторьте `fluentbit_output_retries_total`** — рост ретраев указывает на проблемы с бэкендом.

### См. также

- [Обзор системы логирования](./logging_overview.md)
- [Fluent Bit в Kubernetes](../../../Kubernetes/MonitoringLogging/EFK/fluentbit/fluentbit_configuration.md)
- [Fluent Bit + Loki](../../../Loki/fluentbit_integration.md)
- [Fluent Bit: Scaling и HA](../../../Kubernetes/MonitoringLogging/EFK/efk_fluentbit_scaling.md)
