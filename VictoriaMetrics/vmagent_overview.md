# vmagent: агент сбора и доставки метрик

**Актуально для:** VictoriaMetrics v1.154.x

## Определения

**vmagent** — легковесный агент VictoriaMetrics для сбора и пересылки метрик. Позиционируется как замена Prometheus в роли «сборщика» (scraper) и приёмника данных (receiver) без локального TSDB: он не хранит данные у себя, а отправляет их в одно или несколько хранилищ по протоколу Remote Write. Работает как в режиме Pull (скрейпит HTTP-эндпоинты/экспортеры), так и в режиме Push (принимает данные по Prometheus Remote Write, OpenTelemetry, InfluxDB, Graphite, OpenMetrics).

**Persistent Queue (постоянная очередь)** — буферизация данных на диске при недоступности удалённого хранилища. Отличает vmagent от «голого» Prometheus agent-mode: при обрыве связи ни один сэмпл не теряется, пока очередь не переполнится.

**Streaming Aggregation (Enterprise)** — агрегация данных в реальном времени на стороне агента до их отправки в хранилище (снижает кардинальность и объём передаваемых данных).

**Relabeling** — набор правил преобразования меток (добавление, удаление, переименование, фильтрация) до и после скрейпинга.

## Установка и настройка

### Системные требования

- **ОС:** Linux (x86_64, ARM64, ARM32), macOS, Windows; в production — bare-metal или Linux-контейнер.
- **Архитектура:** vmagent поддерживает IoT-среды: 32-bit ARM, 64-bit ARM, PPC64, 386, AMD64.
- **Порты (по умолчанию):** HTTP `:8429` — scraping API, `/targets`, `/metrics`.
- **Файлы:** один бинарник `vmagent` + YAML-конфиг скрейпинга (формат совместим с Prometheus).

### Способы установки

**1. Бинарник (production):**

```bash
wget https://github.com/VictoriaMetrics/VictoriaMetrics/releases/download/v1.154.0/vmutils-linux-amd64.tar.gz
tar xvf vmutils-linux-amd64.tar.gz
sudo cp vmagent-linux-amd64 /usr/local/bin/vmagent
```

**2. Docker:**

```bash
docker run -d --name vmagent \
  -p 8429:8429 \
  -v $(pwd)/vmagent.yml:/etc/victoriametrics/vmagent.yml:ro \
  victoriametrics/vmagent:v1.154.0 \
  -promscrape.config=/etc/victoriametrics/vmagent.yml \
  -remoteWrite.url=http://victoria-metrics:8428/api/v1/write
```

**3. Kubernetes** — через VictoriaMetrics Operator (CRD `VMAgent`) или Helm-чарт `victoria-metrics-agent`.

### Сервисные файлы (systemd)

Для production на bare-metal используйте systemd (пример с конфигом в сценарии 7 ниже). Убедитесь, что `User` не имеет прав root, а `LimitNOFILE` ≥ 100000.

## Базовые концепции

### Жизненный цикл данных в vmagent

```
Источники (Pull):    exporters, /metrics, kubernetes_sd, file_sd, http_sd
Источники (Push):    OTLP, InfluxDB Line, Graphite, Prometheus remote_write, OpenMetrics
        │
        ▼
   scrape / ingest
        │
        ▼
   relabel_configs (метки до записи) ──┐
        │                              │  -promscrape.relabelConfig
        ▼                              │  -remoteWrite.urlRelabelConfig (per-URL)
   поток в remote_write                │
        │                              │
        ▼                              ▼
   [streamAggr (Enterprise)]   финальные метки
        │
        ▼
   persistent queue (-remoteWrite.tmpDataPath)  ──>  -remoteWrite.url
```

Каждый `-remoteWrite.url` обслуживается собственной очередью: это значит, что задержка или недоступность одного хранилища не блокирует отправку в другие.

### Ключевые флаги запуска

| Флаг | Назначение |
| :--- | :--- |
| `-promscrape.config` | Путь к конфигу скрейпинга (формат как у Prometheus) |
| `-remoteWrite.url` | Адрес хранилища (можно указывать многократно: репликация или шардинг данных) |
| `-remoteWrite.tmpDataPath` | Путь к директории persistent queue (по умолчанию `vmagent-remotewrite-data`) |
| `-remoteWrite.maxDiskUsagePerURL` | Лимит размера очереди на диске для каждого `-remoteWrite.url` |
| `-remoteWrite.queues` | Число воркеров очереди на URL (по умолчанию 2×CPU); регулирует параллельность отправки |
| `-remoteWrite.maxBlockSize` | Максимальный размер блока (batch) для отправки (по умолчанию 8 МБ); уменьшайте при ошибках `413 Payload Too Large` |
| `-remoteWrite.maxRowsPerBlock` | Максимальное число сэмплов в одном блоке (по умолчанию 10000) |
| `-remoteWrite.inmemoryQueues` | Дополнительные in-memory воркеры для свежих данных (с **v1.146.0**), обходят файловый бэклог |
| `-remoteWrite.disableOnDiskQueue` | Отключить on-disk очередь (данные накапливаются в RAM только) |
| `-remoteWrite.dropSamplesOnOverload` | Отбрасывать сэмплы при перегрузке, если очередь отключена |
| `-remoteWrite.flushInterval` | Интервал выгрузки данных в хранилище (по умолчанию 1s) |
| `-remoteWrite.disableMetadata` | Отключить отправку метаданных (типов метрик) в хранилище |
| `-remoteWrite.keepDanglingQueues` | Сохранять очереди при смене `-remoteWrite.url` (иначе старые очереди удаляются) |
| `-remoteWrite.relabelConfig` | Путь к YAML-файлу с global relabeling для всех remote_write (добавление/удаление меток на выходе) |
| `-remoteWrite.urlRelabelConfig` | Пер-URL relabeling — трансформация меток перед отправкой в конкретный `-remoteWrite.url` |
| `-remoteWrite.headers` | Произвольные HTTP-заголовки для запросов к хранилищу (например, `X-Auth: token`) |
| `-remoteWrite.basicAuth.*` | Basic Auth для хранилища |
| `-remoteWrite.bearerToken[File]` | Bearer token аутентификация |
| `-remoteWrite.tls*` | TLS-настройки (CA, сертификат, ключ, InsecureSkipVerify) |
| `-remoteWrite.forceVMProto` | Жёстко использовать VictoriaMetrics remote write protocol (по умолчанию включён с v1.116.0) |
| `-remoteWrite.forcePromProto` | Жёстко использовать Prometheus Remote Write 1.0 |
| `-remoteWrite.vmProtoCompressLevel` | Уровень сжатия VM-протокола (больше — меньше трафика, больше CPU; отрицательные — наоборот) |
| `-remoteWrite.significantFigures` | Округление значений метрик (число значащих цифр) |
| `-remoteWrite.roundDigits` | Округление значений метрик (число десятичных знаков) |
| `-remoteWrite.maxHourlySeries` / `-remoteWrite.maxDailySeries` | Лимиты уникальных серий (rate limiting) |
| `-remoteWrite.streamAggr.config` | Файл конфигурации Streaming Aggregation (Enterprise) |
| `-promscrape.configCheckInterval` | Периодическая перезагрузка конфига без рестарта |
| `-httpListenAddr` | Адрес HTTP-сервера, по умолчанию `:8429` |
| `-httpAuth.*`, `-metricsAuthKey`, `-tls*` | Аутентификация/TLS самого агента |

### Режимы доставки данных

1. **Направление в одно хранилище** — классический сценарий, когда VictoriaMetrics выступает долгосрочным хранилищем для Prometheus-ов.
2. **Репликация** — несколько одинаковых `-remoteWrite.url`: каждый сэмпл отправляется во все хранилища (дубликаты дедуплигируются на стороне VictoriaMetrics через `-dedup.minScrapeInterval`).
3. **Шардинг** — `-remoteWrite.shardByURL` и `-remoteWrite.shardByURLReplicas`: каждая серия отправляется в N из M хранилищ, что даёт отказоустойчивость при меньшем расходе диска, чем полная репликация.
4. **Прямая запись в vmstorage** — vmagent может писать данные напрямую на ноды `vmstorage` по протоколу Remote Write v1 (требует `-enableIngestionAPI` на vmstorage и URL формата `http://<vmstorage>:8482/insert/<tenant_id>/prometheus/api/v1/write`). Поведует как `vminsert` с `-replicationFactor=2` и `-disableReroutingOnUnavailable`: каждая нода имеет собственную очередь, данные не рероутятся на другие ноды при медленной/недоступной vmstorage. Сочетается с `-remoteWrite.shardByURL` и `-remoteWrite.shardByURLReplicas` для контроля репликации.

Для HA-пар vmagent из двух инстансов добавьте `external_labels` в секцию `global` скрейпинг-конфига (например, `replica: "vmagent-a"` на первом инстансе, `vmagent-b` — на втором) или используйте `-remoteWrite.relabelConfig` для глобального relabeling перед отправкой в хранилище. На стороне хранилища включите дедупликацию с `-dedup.minScrapeInterval`, равным скрейп-интервалу.

### Отличие от Prometheus (agent mode) и Prometheus Agent

| Критерий | vmagent | Prometheus Agent Mode |
| :--- | :--- | :--- |
| Pull (scraping) | Да, полный набор service discovery | Ограниченный набор |
| Push (приём) | OTLP, InfluxDB, Graphite, OpenMetrics, remote write | Нет |
| Локальный TSDB | Нет (только буфер) | Нет |
| Persistent queue на диске | Да, по умолчанию включена | Нет (только in-memory) |
| Streaming aggregation | Да (Enterprise) | Нет |
| Потребление RAM | Низкое | Среднее |

## Практические сценарии

### 1. Базовая конфигурация скрейпинга

```yaml
# vmagent.yml
global:
  scrape_interval: 15s
  scrape_timeout: 10s
  external_labels:
    cluster: "prod-eu"

scrape_configs:
  - job_name: node
    static_configs:
      - targets: ["node1:9100", "node2:9100"]

  - job_name: k8s-pods
    kubernetes_sd_configs:
      - role: pod
    relabel_configs:
      - source_labels: [__meta_kubernetes_pod_annotation_prometheus_io_scrape]
        action: keep
        regex: "true"
```

```bash
vmagent -promscrape.config=/etc/victoriametrics/vmagent.yml \
  -remoteWrite.url=http://victoria-metrics:8428/api/v1/write
# Проверка состояния таргетов:
curl -s http://localhost:8429/targets | jq .
```

Доступные типы service discovery: `static_configs`, `file_sd_configs`, `http_sd_configs`, `dns_sd_configs`, `kubernetes_sd_configs` (roles: pod, service, endpoints, node, ingress), `ec2_sd_configs`, `consul_sd_configs`, `nomad_sd_configs` и др.

### 2. Relabeling: фильтрация и нормализация меток

```yaml
scrape_configs:
  - job_name: api
    static_configs:
      - targets: ["api:9191"]

    # Правила до записи: удалить высококардинальные метки на источнике
    relabel_configs:
      - source_labels: [__address__]
        target_label: instance
        regex: "(.*):.*"
        replacement: "${1}"

    # Правила после записи: отбросить нерелевантные метрики на уровне агента
    metric_relabel_configs:
      - source_labels: [__name__]
        regex: "go_gc_.*"
        action: drop
      - source_labels: [request_id]
        action: labeldrop
```

Порядок применения: `relabel_configs` — до записи выбранного таргета; `metric_relabel_configs` — после скрейпинга, к каждой метрике. Динамические лейблы (`request_id`, `trace_id`, IP) обязательно вычищайте здесь же, иначе они станут источником взрыва кардинальности в хранилище.

### 3. Persistent queue и расчёт места под буфер

vmagent по умолчанию записывает неотправленные данные на диск во временную директорию `-remoteWrite.tmpDataPath` и разгребает её по мере восстановления связи.

```bash
vmagent \
  -remoteWrite.url=http://victoria-metrics:8428/api/v1/write \
  -remoteWrite.tmpDataPath=/var/lib/vmagent/queue \
  -remoteWrite.maxDiskUsagePerURL=5GiB \
  -remoteWrite.queues=8
```

- При перегрузке хранилища с отключённой очередью возвращается `429 Too Many Requests`; с флагом `-remoteWrite.dropSamplesOnOverload` сэмплы молча отбрасываются.
- При достижении `-remoteWrite.maxDiskUsagePerURL` агент отбрасывает самые старые сэмплы (метрика `vmagent_remotewrite_samples_dropped_total`).
- `-remoteWrite.inmemoryQueues` (доступен с v1.146.0) добавляет «горячие» in-memory воркеры, которые доставляют свежие данные, не дожидаясь выгребания файлового бэклога — снижает лаг для новых метрик после длительного простоя хранилища.
- При работе с хранилищами, не принимающими out-of-order данные (Prometheus, Mimir, Thanos Receiver), используйте `-remoteWrite.queues=1`.

Размер очереди для планирования: `число_сэмплов_в_сек × пиковое_время_простоя_в_сек × ~2КБ`.

### 4. Приём данных по push-протоколам

Помимо скрейпинга vmagent принимает данные напрямую (по умолчанию на `:8429`):

| Протокол | Эндпоинт |
| :--- | :--- |
| Prometheus Remote Write (snappy) | `POST /api/v1/write` |
| OpenTelemetry (OTLP/HTTP) | `POST /opentelemetry/v1/metrics` |
| InfluxDB Line Protocol | `/influx/write`, `/influx/api/v1/write` |
| Graphite | `/graphite/write` |
| Prometheus Text Exposition / OpenMetrics | `/metrics` |

Это позволяет использовать vmagent как «единую точку приёма» для разнородных источников и затем нормализовать/отправлять всё в центральное хранилище.

### 5. Streaming Aggregation (Enterprise)

```bash
vmagent \
  -remoteWrite.url=http://victoria-metrics:8428/api/v1/write \
  -remoteWrite.streamAggr.config=/etc/victoriametrics/stream-aggr.yml \
  -remoteWrite.streamAggr.dedupInterval=5s
```

```yaml
# stream-aggr.yml
- match: "{__name__=~\"job_cpu_\",job=~\"prod.*\"}"
  interval: 1m
  outputs: ["sum", "count"]
  by: ["job", "instance"]
- match: "*"
  interval: 1m
  outputs: ["sum"]
  by: ["__name__"]
```

Агрегирует «сырые» сэмплы внутри агента за окно `interval` и отправляет в хранилище только итоги. При той же точности алертинга и дашбордов радикально снижает кардинальность и расход диска. Доступно только в Enterprise-редакции.

### 6. HA-схема с двумя агентами

```yaml
# vmagent replica 1 и 2 — одинаковая конфигурация, отличаются меткой replica
global:
  external_labels:
    replica: "vmagent-a"   # на втором инстансе — vmagent-b
scrape_configs:
  - job_name: node
    static_configs:
      - targets: ["node:9100"]
```

```bash
# На хранилище (single-node или кластер):
victoria-metrics -storageDataPath=... -dedup.minScrapeInterval=15s
```

Дедупликация на стороне VictoriaMetrics по одинаковым timestamp-ам из двух агентов. Дублирующий скрейпинг допустим: цена — удвоенный сетевой трафик, зато нет потери данных при падении одного агента.

### 7. Деплой на bare-metal (systemd) и в Kubernetes

**systemd-сервис `/etc/systemd/system/vmagent.service`:**

```ini
[Service]
User=vmagent
ExecStart=/usr/local/bin/vmagent \
  -promscrape.config=/etc/victoriametrics/vmagent.yml \
  -remoteWrite.url=http://victoria-metrics:8428/api/v1/write \
  -remoteWrite.url=http://victoria-metrics-ha2:8428/api/v1/write \
  -remoteWrite.tmpDataPath=/var/lib/vmagent/queue \
  -remoteWrite.maxDiskUsagePerURL=5GiB \
  -promscrape.configCheckInterval=30s
Restart=always
RestartSec=5
LimitNOFILE=100000

[Install]
WantedBy=multi-user.target
```

**Kubernetes** — см. [VictoriaMetrics Operator](./operator_overview.md): CRD `VMAgent` поддерживает `replicaCount`, `sharding`, `statefulMode` для сохранения persistent queue на StatefulSet-PVC (иначе после перезапуска пода буфер теряется).

### 8. Протокол Remote Write: как vmagent упаковывает данные

Общая картина (детали протокола и версий — SSoT в [Prometheus: Remote Read/Write](./../Prometheus/scaling/remote_read_write.md)):

- vmagent собирает сэмплы и шлёт на `vminsert`/single-node по `POST /api/v1/write` протоколом **Prometheus Remote Write** (PRW 1.0): серии сериализуются в protobuf `WriteRequest`, пакет сжимается **snappy** и отправляется с `Content-Encoding: snappy`, `Content-Type: application/x-protobuf` (версия протокола — заголовок `X-Prometheus-Remote-Write-Version: 0.1.0`).
- **Prometheus Remote Write 2.0** — спецификация опубликована в мае 2024 года (версия 2.0-rc.4, статус: **экспериментальный**). Добавляет интернирование строк, поддержку `zstd`, передачу метаданных о типах метрик и created timestamps. **VictoriaMetrics на данный момент не поддерживает PRW 2.0** (см. SSoT для деталей протокола в [Prometheus: Remote Read/Write](./../Prometheus/scaling/remote_read_write.md)).
- **VictoriaMetrics Remote Write protocol** (по умолчанию с **v1.116.0**): vmagent использует собственный протокол записи VictoriaMetrics, который снижает дисковый IOPS и сетевой трафик на **2–5×** по сравнению с PRW 1.0 за счёт более эффективной сериализации. При недоступности VM-протокола агент автоматически откатывается на PRW 1.0. Управление: `-remoteWrite.forceVMProto` (жёстко включить), `-remoteWrite.forcePromProto` (жёстко переключить на PRW), `-remoteWrite.vmProtoCompressLevel` (уровень сжатия: больше — меньше трафика, больше CPU).
- Приёмник отдаёт `204` на приём блокa; любые HTTP-ошибки (413/400/429 и др.) учитываются vmagent как сбой блока и уходят в retry/очередь.

Практические следствия:

- **snappy ≠ gzip**: клиенты, которые шлют gzip-вариант, получат `400` — VM не примет такой запрос. В тестах `curl` сжимайте корректно или используйте непотоковый формат.
- **Число соединений/очередей** регулируется `-remoteWrite.queues` (по умолчанию 2× число CPU) и `-remoteWrite.maxBlockSize` (по умолчанию 8 МБ) — при «растущей задержке» увеличивайте их и добавляйте `-remoteWrite.inmemoryQueues` (см. проблема ниже в таблице).
- **Совместимость со sidecar-migrations**: Prometheus Agent Mode и vmagent используют один и тот же протокол; для Mimir/Thanos (которые ждут PRW) может понадобиться `-remoteWrite.queues=1` — порядок сэмплов важен.

## Валидация установки

```bash
# Состояние таргетов (UP/DOWN) и ошибки скрейпа
curl -s http://localhost:8429/targets | jq .
# → {"scrapePool":"node","targets":[{"labels":{...},"discoveredLabels":{...}}],...}

# Собственные метрики
curl -s http://localhost:8429/metrics | grep -E "^vmagent_remotewrite"

# Метрики очередей
curl -s http://localhost:8429/metrics | grep -E "^vm_persistentqueue_"
# → vm_persistentqueue_bytes_pending{path="...",url="..."} 0
```

- **`vmagent_remotewrite_queue_blocked`** — 1, если очередь заблокирована (хранилище не успевает); используйте для алерта на перегрузку.
- **`vmagent_remotewrite_errors_total`** — число HTTP-ошибок при отправке в хранилище (транспортные проблемы, аутентификация).
- **`vmagent_remotewrite_retries_count_total`** — число попыток повторной отправки (растёт при недоступности хранилища).
- **`vmagent_remotewrite_samples_dropped_total`** — число потерянных сэмплов из-за переполнения буфера или ошибок.
- **`vmagent_remotewrite_rows_pushed_after_relabel_total`** — число сэмплов, отправленных в хранилище (нулевое значение → проблема на агенте или в сети).
- **`vmagent_remotewrite_block_size_bytes` / `vmagent_remotewrite_block_size_rows`** — гистограммы размера батчей (для отладки 413 и throughput).
- **`vmagent_remotewrite_pending_data_bytes`** — объём накопленных в очереди данных в байтах.
- **`vmagent_scrapes_total` / `vmagent_scrape_errors_total`** — успешность скрейпинга.
- **`vm_persistentqueue_bytes_pending`** / **`vm_persistentqueue_read_duration`** — актуальный объём накопленного в очереди.

Для self-monitoring: vmagent скрейпит самого себя через `/metrics` на `:8429`. Ключевые алерты — на `vmagent_remotewrite_queue_blocked == 1` (перегрузка хранилища), `rate(vmagent_remotewrite_samples_dropped_total[5m]) > 0` (потеря данных) и `vmagent_scrape_errors_total > 0` (проблемы со скрейпингом).

## Операции и команды

### Управление конфигурацией

| Действие | Команда |
| :--- | :--- |
| Перезагрузка конфига без рестарта | автоматически (раз в `-promscrape.configCheckInterval`), либо `kill -HUP <PID>`, либо `curl -X POST http://localhost:8429/-/reload` (с `-reloadAuthKey`) |
| Проверка конфига на ошибки | `vmagent -promscrape.config=/path/to/config.yml -promscrape.configCheckInterval=0` (старт в обычном режиме — при ошибке конфига процесс завершится с описанием проблемы); периодическая перезагрузка через `/-/reload` также валидирует конфиг на каждую итерацию |
| Просмотр всех флагов | `vmagent -help` |

Перезагружаются следующие конфиги: `-promscrape.config`, `-remoteWrite.relabelConfig`, `-remoteWrite.urlRelabelConfig`, `-streamAggr.config`, `-remoteWrite.streamAggr.config`.

### Мониторинг и отладка

| Запрос | Что показывает |
| :--- | :--- |
| `GET /targets` | Список всех таргетов, их статус UP/DOWN, ошибки |
| `GET /metrics` | Метрики самого vmagent (Prometheus exposition format) |
| `GET /debug/pprof/` | Профилирование CPU, памяти, горутин |

### Перезапуск и обновление

```bash
# Graceful shutdown (данные в очереди сбрасываются)
kill -TERM <PID>

# Rolling update (Docker / k8s)
docker stop vmagent && docker run ... # новая версия
# persistent queue сохраняется на диске — данные не теряются

# Проверка статуса
systemctl status vmagent
journalctl -u vmagent -f
```

## Поиск и устранение неисправностей

| Проблема | Причина | Диагностика и решение |
| :--- | :--- | :--- |
| Данные пропадают | Очередь переполнена (`maxDiskUsagePerURL`) | Проверить `vmagent_remotewrite_samples_dropped_total`; увеличить лимит/`queues`, проверить хранилище |
| Растущая задержка доставки | Хранилище не успевает; FIFO-порядок очереди | Увеличить `-remoteWrite.queues`/`-remoteWrite.maxBlockSize`; добавить `-remoteWrite.inmemoryQueues` |
| Таргеты в состоянии DOWN | Сеть/экспортер недоступен; неверный relabel | `curl /targets`, `journalctl -u vmagent`; проверить firewall и `scrape_timeout` |
| Высокий RAM | Много таргетов, большая очередь, медленные запросы | `vmagent_*_memory`; уменьшить параллелизм скрейпа, задать `-memory.allowedPercent` |
| Дубли в хранилище | Нет дедупликации | Включить `-dedup.minScrapeInterval` в VictoriaMetrics, проверить `external_labels` |
| Ошибки аутентификации | basicAuth/bearerToken не передаются или неверны | Проверить `-remoteWrite.basicAuth.*`, `-remoteWrite.bearerToken[File]`, `-remoteWrite.tls*` |
| Конфиг не перезагружается | `-promscrape.configCheckInterval=0` (выключено) или синтаксическая ошибка | Увеличить интервал; проверить конфиг, стартовав vmagent с ним (при ошибке процесс завершится с описанием проблемы); отправить `SIGHUP` или `curl -X POST http://localhost:8429/-/reload` |
| 413 Payload Too Large | Слишком большой batch | Уменьшить `-remoteWrite.maxBlockSize`, увеличить `-remoteWrite.queues` |
| Метрики не появляются в хранилище | Неверный URL `/api/v1/write`, firewall | Проверить `vmagent_remotewrite_rows_pushed_after_relabel_total` (отправка нулевая → проблема на агенте) |
| Высокая нагрузка на диск очереди | Большой `-remoteWrite.tmpDataPath`, мало `queues` | Убедиться, что диск выдерживает IOPS; добавить `-remoteWrite.inmemoryQueues` для свежих данных |

## Рекомендации по эксплуатации

- **Всегда** выделяйте persistent queue (`-remoteWrite.tmpDataPath` + лимит) в production: это защита от кратковременной недоступности хранилища.
- Мониторьте очередь (алерт на `vmagent_remotewrite_queue_blocked == 1` за 10 минут).
- Вычищайте высококардинальные метки через `relabel_configs`/`metric_relabel_configs` ещё на агенте — это главная защита от «взрыва кардинальности».
- Настраивайте `-promscrape.configCheckInterval` (или SIGHUP через `kill -HUP`) для бесшовного обновления конфига.
- vmagent поддерживает rolling upgrade без потери очереди — обновляйте без остановки.
- Увеличивайте `ulimit -n` (открытые файлы) при большом числе таргетов (не менее 65535).

## Ограничения и особые случаи

- Persistent queue не гарантирует отсутствие потерь при переполнении — это «лучшее усилие», а не WAL.
- При `-remoteWrite.disableOnDiskQueue` возможно повторное попадание одних и тех же сэмплов в хранилище — на стороне хранилища должна быть включена дедупликация.
- Streaming Aggregation доступна только в Enterprise-редакции.
- При шардинге через `-remoteWrite.shardByURL` часть хранилищ может не содержать полного набора серий — учитывайте это при построении запросов.

## Дополнительная информация

### См. также

- [VictoriaMetrics: обзор](./overview.md) — роль vmagent в стеке наблюдаемости;
- [Отчёт о кардинальности (vmestimator)](./vmestimator.md) — оценка кардинальности на этапе сбора;
- [Prometheus: Service Discovery и Relabeling](../Prometheus/service_discovery_and_relabeling.md) — общие правила relabeling;
- [VictoriaMetrics Operator](./operator_overview.md) — деплой vmagent в Kubernetes;
- [Prometheus: Remote Read/Write](./../Prometheus/scaling/remote_read_write.md) — SSoT по протоколу Remote Write (PRW 1.0; PRW 2.0 — экспериментальный, не поддерживается VictoriaMetrics);
- [HTTP API VictoriaMetrics](./http_api_reference.md) — эндпоинты приёма `/api/v1/write`, импорт;
- [Enterprise-функции](./enterprise_features.md) — Streaming Aggregation, vmgateway.
