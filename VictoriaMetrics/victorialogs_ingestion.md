# Инжест логов в VictoriaLogs: протоколы и практика

**Актуально для:** VictoriaLogs v1.53.0

## Определения

**Ingestion (приём, инжест)** — процесс доставки логов (строк/JSON) в VictoriaLogs через HTTP-эндпоинты на порту `9428` (`/insert/*`) или через протоколы syslog/journald на выделенных портах. VictoriaLogs не требует предварительной схемы: любое JSON-поле автоматически становится «полем лога» и индексируется для поиска.

**Stream / поток** — логически сгруппированный набор записей с одинаковым набором stream-полей (определяется параметром `_stream_fields` или полем `_stream` в записи). Поток — единица хранения и сжатия: данные одного потока физически располагаются рядом.

**_msg (сообщение)** — специальное поле, содержащее текст лог-сообщения. По умолчанию читается из поля `_msg`; имя поля можно переопределить через query-аргумент `_msg_field` или заголовок `VL-Msg-Field`.

**_time (время)** — метка времени лога. Читается из поля `_time` или переопределяется через `_time_field`/`VL-Time-Field`. Поддерживаемые форматы: ISO8601, RFC3339, Unix timestamp (с/мс/мкс/нс).

**_stream (поток в записи)** — необязательное поле, содержащее явное определение stream-полей, например `{"_stream": "{host=\"abc\",app=\"nginx\"}", ...}`.

## Базовые концепции

### Принципы приёма

- **Schema-less:** любые поля в JSON-записи автоматически индексируются и становятся доступными для поиска (включая high-cardinality поля вроде `trace_id`).
- **In-memory буферизация:** входящие логи копируются в in-memory буферы и сбрасываются на диск каждые ~1 секунду (флаг `-inmemoryDataFlushInterval`, по умолчанию `5s`, минимум `1s`). **WAL (Write-Ahead Log) не используется** — при аварийном завершении (SIGKILL, OOM, отключение питания) теряются только логи, не успевшие попасть в очередной буферный сброс.
- **Stream locality:** логи с одинаковыми stream-полями группируются в потоки и хранятся рядом, что обеспечивает высокую степень сжатия и быстрый поиск.
- **Разделение insert/read:** запись выполняется через `/insert/*`, чтение — через `/select/*`.

### Поддерживаемые протоколы и HTTP API

| Endpoint | Протокол | Назначение |
| :--- | :--- | :--- |
| `/insert/jsonline` | JSON Lines (ndjson) | Универсальный приём JSON-строк |
| `/insert/elasticsearch/_bulk` | Elasticsearch Bulk API | Filebeat, Logstash, Fluent Bit (es output) |
| `/insert/loki/api/v1/push` | Loki JSON API | Promtail, Grafana Alloy |
| `/insert/opentelemetry/v1/logs` | OTLP/HTTP | OpenTelemetry Collector, otlploghttp SDK |
| `/insert/datadog/api/v2/logs` | Datadog API | Datadog Agent (v1.50.0+ также `/api/v2/logs` без префикса) |
| `/insert/splunk/services/collector/event` | Splunk HEC | Splunk HTTP Event Collector |
| `-syslog.listenAddr.tcp/udp/unix` | Syslog (RFC3164/5424) | Прямой приём через флаги, не HTTP-эндпоинт |
| `-journald.*` + systemd-journal-upload | Journald | Прямой приём через systemd-journal-upload |

**Важно:** syslog и journald принимаются не через HTTP-эндпоинты `/insert/*`, а через выделенные флаги командной строки и протоколы транспортировки.

### HTTP-параметры и заголовки

Все параметры можно передать как query-строку (приоритет выше), так и HTTP-заголовками.

**Query-параметры (query string args):**

| Параметр | Описание |
| :--- | :--- |
| `_msg_field` | Поле, из которого берётся сообщение (можно список через `,`) |
| `_time_field` | Поле с меткой времени (можно список через `,`) |
| `_stream_fields` | Поля, по которым строится поток (через `,`) |
| `ignore_fields` | Поля для игнорирования (поддерживает префиксы `prefix*`) |
| `decolorize_fields` | Удалить ANSI-коды цвета из перечисленных полей |
| `extra_fields` | Добавить поля ко всем логам (`field=value`) |
| `preserve_json_keys` | JSON-ключи, которые не нужно разворачивать |
| `debug=1` | Не сохранять логи, а только залогировать их (для отладки) |

**HTTP-заголовки:**

| Заголовок | Описание |
| :--- | :--- |
| `VL-Msg-Field` | Аналог `_msg_field` через заголовок |
| `VL-Time-Field` | Аналог `_time_field` через заголовок |
| `VL-Stream-Fields` | Аналог `_stream_fields` через заголовок |
| `VL-Ignore-Fields` | Аналог `ignore_fields` через заголовок |
| `VL-Decolorize-Fields` | Аналог `decolorize_fields` через заголовок |
| `VL-Extra-Fields` | Аналог `extra_fields` через заголовок |
| `VL-Preserve-JSON-Keys` | Аналог `preserve_json_keys` через заголовок |
| `VL-Debug` | Аналог `debug=1` через заголовок |
| `AccountID` | Идентификатор тенанта (multitenancy) |
| `ProjectID` | Идентификатор проекта тенанта |

## Установка и первичная настройка

VictoriaLogs — единый бинарный файл, запускается без внешних зависимостей. Подробная установка (systemd, Docker, Kubernetes) описана в [victorialogs_internals.md](./victorialogs_internals.md).

```bash
# Скачивание и запуск (пример для Linux amd64)
wget https://github.com/VictoriaMetrics/VictoriaLogs/releases/download/v1.53.0/victoria-logs-linux-amd64-v1.53.0.tar.gz
tar xzf victoria-logs-linux-amd64-v1.53.0.tar.gz
./victoria-logs-prod -storageDataPath=/var/lib/victorialogs -retentionPeriod=30d
```

```bash
# Проверка health
curl -s http://localhost:9428/health
# → OK
```

**Ключевые флаги для приёма логов:**

| Флаг | Описание | По умолчанию |
| :--- | :--- | :--- |
| `-storageDataPath` | Директория данных | `./victoria-logs-data` |
| `-httpListenAddr` | HTTP-адрес | `:9428` |
| `-retentionPeriod` | Период хранения | `7d` |
| `-retention.maxDiskSpaceUsageBytes` | Жёсткий лимит диска | — |
| `-inmemoryDataFlushInterval` | Интервал сброса буферов | `5s` |
| `-insert.maxLineSizeBytes` | Макс. размер строки | `256KiB` |
| `-syslog.listenAddr.tcp` | TCP порт для syslog | — |
| `-syslog.listenAddr.udp` | UDP порт для syslog | — |
| `-journald.streamFields` | Stream-поля для journald | `_HOSTNAME,_SYSTEMD_UNIT,_MACHINE_ID` |
| `-syslog.streamFields` | Stream-поля для syslog | — |

## Практические сценарии

### 1. Прямая отправка JSON Lines (curl)

```bash
curl -X POST http://localhost:9428/insert/jsonline \
  -H 'Content-Type: application/stream+json' \
  -d '{"_msg":"hello from JSON","level":"info","host":"web-1"}'
```

Каждая строка — отдельный лог. Поле `_time` можно не указывать: VictoriaLogs возьмёт время получения. Поле `_msg` можно переопределить через `?_msg_field=message`:

```bash
curl -X POST 'http://localhost:9428/insert/jsonline?_stream_fields=host,level' \
  -H 'Content-Type: application/stream+json' \
  -d '{"message":"server started","level":"info","host":"web-1"}'
```

**Пакетная отправка с транзакционной семантикой:**

```bash
# Отправка нескольких строк за один запрос (JSON Lines)
cat logs.jsonl | curl -X POST \
  -H 'Content-Type: application/stream+json' \
  --data-binary @- \
  'http://localhost:9428/insert/jsonline?_stream_fields=host,service'
```

### 2. Безопасность: vmauth и nginx

Доступ к `/insert/*` должен быть закрыт для внешних пользователей.

```yaml
# Конфигурация vmauth (маршрутизация с аутентификацией)
users:
  - username: logger
    password: secret
    url_prefix: http://victorialogs:9428/
    url_map:
      - src_paths: ["/insert/.*"]
        headers:
          - "AccountID: 0"
          - "ProjectID: 0"
        url_prefix: http://victoria-logs:9428/
```

```nginx
# nginx: ограничение доступа по IP
location /insert/ {
    allow 10.0.0.0/8;
    deny all;
    proxy_pass http://victorialogs:9428;
}
```

### 3. Сбор логов journald (systemd-journal-upload)

VictoriaLogs поддерживает прямой приём journald через `systemd-journal-upload`:

```bash
# Запуск VictoriaLogs с приёмом journald на порту 9428
./victoria-logs \
  -storageDataPath=/var/lib/victorialogs \
  -journald.streamFields=_HOSTNAME,_SYSTEMD_UNIT,_MACHINE_ID

# /etc/systemd/journal-upload.conf
[Journal]
URL=http://localhost:9428
```

Из официальных документов: `systemd-journal-upload` v258+ поддерживает заголовки `VL-Stream-Fields`, `VL-Msg-Field`, `AccountID`, `ProjectID` для динамической настройки без перезапуска.

### 4. Сбор логов syslog (rsyslog, syslog-ng)

VictoriaLogs принимает syslog через выделенные порты (не HTTP), управляемые флагами:

```bash
# Приём syslog по TCP на порту 514
./victoria-logs \
  -syslog.listenAddr.tcp=:514 \
  -syslog.streamFields=host \
  -syslog.timezone=Europe/Moscow

# Для TLS (Enterprise)
./victoria-logs -syslog.listenAddr.tcp=:514 -syslog.tls=true
```

**rsyslog → VictoriaLogs (пересылка в syslog):**

```bash
# /etc/rsyslog.d/30-victorialogs.conf
*.* action(type="omfwd"
  Target="victorialogs.example.com"
  Port="514"
  Protocol="tcp"
  TCP_Framing="octet-count"
)
```

**syslog-ng → VictoriaLogs:**

```syslog-ng
# /etc/syslog-ng/conf.d/victorialogs.conf
destination d_victorialogs {
  syslog("victorialogs.example.com" port(514) transport(tcp));
};
log { source(s_local); destination(d_victorialogs); };
```

VictoriaLogs автоматически извлекает из syslog-сообщений поля `_time`, `msg_id` и структурированные данные (SD).

### 5. Vector → VictoriaLogs

```toml
# vector.toml
[sources.journald]
type = "journald"

[transforms.norm]
type = "remap"
inputs = ["journald"]
source = '''
.meta = { "service" = "journald", "host" = ._HOSTNAME ?? .host }
'''

[sinks.vl]
type = "http"
inputs = ["norm"]
uri = "http://victorialogs:9428/insert/jsonline?_stream_fields=service,host"
encoding.codec = "json"
```

### 6. OpenTelemetry Collector → OTLP

```yaml
# otel-collector.yaml
exporters:
  otlphttp:
    endpoint: http://victorialogs:9428/insert/opentelemetry/v1/logs
    headers:
      VL-Stream-Fields: "host,app"   # переопределить stream-поля
      VL-Ignore-Fields: "foo,bar"    # игнорировать поля

receivers:
  filelog:
    include: [/var/log/*.log]
    resource:
      host: ${ENV_HOSTNAME}
      app: myapp
    operators:
      - type: json_parser
        id: json_parser
        fields: [level, msg]

service:
  pipelines:
    logs:
      receivers: [filelog]
      exporters: [otlphttp]
```

Go-SDK с `otlploghttp.WithHeaders`:

```go
logExporter, err := otlploghttp.New(ctx,
  otlploghttp.WithEndpointURL("http://victorialogs:9428/insert/opentelemetry/v1/logs"),
  otlploghttp.WithHeaders(map[string]string{
    "VL-Stream-Fields": "host,app",
  }),
)
```

### 7. vlagent (Kubernetes)

Для Kubernetes рекомендуется использовать **vlagent** — лёгкий агент для сбора контейнерных логов. Подробная настройка в [victorialogs_k8s_setup.md](./../Kubernetes/MonitoringLogging/victorialogs_k8s_setup.md).

```yaml
# Краткая конфигурация vlagent (DaemonSet)
vlagent:
  remoteWrite:
    - url: http://victoria-logs:9428/insert/jsonline?_stream_fields=pod,container,namespace
      headers:
        VL-Ignore-Fields: "kubernetes.pod_ip,kubernetes.node_name"
```

### 8. Filebeat → Elasticsearch Bulk API

```yaml
# filebeat.yml
output.elasticsearch:
  hosts: ["http://victorialogs:9428"]
  index: "insert/elasticsearch"  # → /insert/elasticsearch/_bulk
  bulk_max_size: 1024
  headers:
    VL-Stream-Fields: "host,service"
```

### 9. Promtail → Loki JSON API

```yaml
# promtail.yaml
clients:
  - url: http://victorialogs:9428/insert/loki/api/v1/push
    # VictoriaLogs принимает стандартный Loki push API без модификаций
```

### 10. Datadog Agent

```yaml
# datadog-agent.yaml
logs_config:
  logs_dd_url: http://victorialogs:9428
  use_http: true
  # v1.50.0+: также поддерживаются пути /api/v2/logs и /api/v1/validate без префикса
```

### 11. Splunk HEC

```bash
# Отправка через Splunk HEC API
curl -X POST -H 'Content-Type: application/json' \
  -H 'Authorization: Splunk <token>' \
  http://victorialogs:9428/insert/splunk/services/collector/event \
  -d '{"host":"web-1","source":"myapp","sourcetype":"app","event":"error occurred"}'
```

## Операции: мониторинг и валидация

### Метрики приёма

Ключевые метрики на `http://localhost:9428/metrics` (полный справочник — [документация](https://docs.victoriametrics.com/victorialogs/metrics/)):

| Метрика | Описание |
| :--- | :--- |
| `vl_rows_ingested_total{type=...}` | Принято записей (jsonline, loki, elasticsearch, datadog, opentelemetry, journald, syslog) |
| `vl_bytes_ingested_total{type=...}` | Принято байт по протоколам |
| `vl_rows_dropped_total{reason=...}` | Отброшено записей (too_many_fields, too_big_timestamp, too_small_timestamp) |
| `vl_too_long_lines_skipped_total` | Строки превышающие `-insert.maxLineSizeBytes` |
| `vl_streams_created_total` | Создано потоков (индикатор high cardinality) |
| `vl_pending_rows{type="storage"}` | Записей в буфере ожидающих сброса на диск |
| `vl_http_errors_total{path=...}` | Ошибки HTTP по эндпоинтам |
| `vl_insert_active_streams` | Уникальных потоков в памяти vlinsert (cluster) |

### Валидация установки

```bash
# 1) Health check
curl -s http://localhost:9428/health
# → OK

# 2) Отправка тестовой записи и чтение обратно
echo '{"_msg":"test","level":"debug"}' | \
  curl -s -X POST -H 'Content-Type: application/stream+json' --data-binary @- \
  http://localhost:9428/insert/jsonline
curl -sG 'http://localhost:9428/select/logsql/query' \
  --data-urlencode 'query=_time:5m level:"debug"' | jq .

# 3) Принудительный flush для немедленной доступности (v1.53.0: POST)
curl -X POST http://localhost:9428/internal/force_flush
# → OK
```

## Поиск и устранение неисправностей

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| `422 Unprocessable Entity` | Не JSON Lines (нет `\n` между записями) | Проверить `Content-Type: application/stream+json`, наличие переводов строк |
| `413 Request Entity Too Large` | Большой batch | Разбить на пакеты (1–10 МБ); `-insert.maxLineSizeBytes` для больших строк |
| `401/403` | Ограничение доступа | Проверить IP-фильтры, vmauth, Basic Auth (`-httpAuth.*`) |
| Данные не появляются в запросах | `VL-Ignore-Fields` перечислил поле; источник пишет в другой поток | Проверить `stream_fields`/`VL-Stream-Fields`; `debug=1` для трассировки |
| Данные не появляются сразу | in-memory буфер не сброшен | Ждать ~1 секунду или вызвать `POST /internal/force_flush` |
| Много потоков (high cardinality) | `_stream_fields` выбран неудачно (например, `trace_id`) | Выбрать низкокардинальные поля: `host`, `service`, `env` |
| `vl_rows_dropped_total{reason="too_small_timestamp"}` | Старые метки времени | Согласовать часы источников; проверить `-retentionPeriod` |
| `vl_too_long_lines_skipped_total > 0` | Строки превышают лимит | Увеличить `-insert.maxLineSizeBytes` (максимум 2 MB) или разбить payload |
| `/internal/force_flush` возвращает 405 Method Not Allowed | v1.53.0: endpoint требует POST | Использовать `curl -X POST`, а не GET |
| Syslog/journald не принимаются | Флаги listenAddr не заданы | Проверить `-syslog.listenAddr.*` или journald-флаги при запуске |

### Диагностические команды

```bash
# Трассировка ingestion для отладки
curl -X POST 'http://localhost:9428/insert/jsonline?debug=1' \
  -H 'Content-Type: application/stream+json' \
  -d '{"_msg":"debug message","level":"info"}'
# → лог появляется в stdout VictoriaLogs, не сохраняется

# Логирование новых потоков (временно, 10 сек)
curl -X POST 'http://localhost:9428/internal/log_new_streams?seconds=10'

# Метрики приёма
curl -s http://localhost:9428/metrics | grep -E '^vl_(rows_ingested_total|rows_dropped_total|too_long_lines|streams_created_total|pending_rows)'
```

## Рекомендации по эксплуатации

- **Stream-поля:** используйте низкокардинальные стабильные идентификаторы (`host`, `service`, `env`, `pod`, `container`). Высококардинальные значения (`trace_id`, `user_id`, `request_id`) — обычные поля, не stream-поля.
- **Retention:** настраивайте через `-retentionPeriod` (временной) и `-retention.maxDiskSpaceUsageBytes` (дисковый лимит). Приоритет дискового лимита выше.
- **Размер строк:** увеличивайте `-insert.maxLineSizeBytes` для stacktraces, но не превышайте 2 MB. Разбивайте большие payload на части на уровне коллектора.
- **Бэкап:** только через снимки партиций (`/internal/partition/snapshot/create`) + rsync/rclone, или `vmbackup` для cluster-режима.
- **Мониторинг:** алерты на `rate(vl_rows_dropped_total[5m]) > 0`, `vl_streams_created_total` растёт быстрее, чем ожидалось, `vl_storage_is_read_only = 1`.
- **Аутентификация:** всегда ставьте `vmauth` или reverse proxy перед `/insert/*`; используйте `-httpAuth.*` или заголовки `AccountID`/`ProjectID` для мультитенантности.

## Ограничения и особые случаи

- **Нет WAL и транзакций:** приём работает по принципу «best effort» + in-memory буферизация. При сбое пакет может быть принят частично; для строгой гарантии используйте retry на клиенте. Окно потерь ограничено `-inmemoryDataFlushInterval` (по умолчанию 5 секунд).
- **Лимиты размера:** максимальный размер строки — 2 MB (жёстко зашит в код); `-insert.maxLineSizeBytes` только снижает порог (по умолчанию 256 KiB). Максимум полей на строку: 1000 (`-insert.maxFieldsPerLine`).
- **Internal endpoints v1.53.0:** `/internal/force_merge`, `/internal/force_flush`, `/internal/log_new_streams`, `/internal/partition/*` требуют метода POST (ранее GET допускался).
- **Syslog и journald:** принимаются только через выделенные флаги командной строки, не через `/insert/*`.

## Дополнительная информация

### См. также

- [VictoriaLogs: внутреннее устройство](./victorialogs_internals.md) — архитектура, хранилище, партиции, настройка deployment;
- [LogsQL: обзор](./logsql_overview.md) — язык запросов, фильтры, пайпы, агрегации;
- [vmauth: прокси и аутентификация](./vmauth_overview.md) — защита `/insert/*`, мультитенантность;
- [vmbackup/vmrestore](./vmbackup_restore.md) — бэкап и восстановление для cluster-режима;
- [Развёртывание VictoriaLogs в Kubernetes](./../Kubernetes/MonitoringLogging/victorialogs_k8s_setup.md) — Helm, operator, vlagent;
- [Документация data ingestion](https://docs.victoriametrics.com/victorialogs/data-ingestion/) — официальные гайды по каждому протоколу;
- [Metrics of VictoriaLogs](https://docs.victoriametrics.com/victorialogs/metrics/) — справочник метрик.
