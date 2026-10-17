# vmctl: миграция исторических данных в VictoriaMetrics

**Актуально для:** VictoriaMetrics v1.154.x

## Определения

**vmctl** — CLI-утилита VictoriaMetrics для переноса исторических метрик в VictoriaMetrics из Prometheus (snapshot), InfluxDB, OpenTSDB, Thanos (snapshot), Mimir/Cortex/Promscale (через Prometheus Remote Read) и между инстансами VictoriaMetrics без простоя. Также поддерживает проверку экспортированных блоков (`verify-block`).

**Native mode (`vmctl vm-native`)** — самый быстрый способ переноса между VictoriaMetrics: работает напрямую между VM-совместимыми серверами, копируя уже упакованные блоки данных по бинарному native-протоколу (`/api/v1/export/native` → `/api/v1/import/native`) без перекодировки.

**Remote Read mode (`vmctl remote-read`)** — перенос данных из источников, поддерживающих Prometheus Remote Read API (Cortex, Mimir, Promscale, Thanos через прокси).

**Prometheus mode (`vmctl prometheus`)** — перенос из локального снапшота TSDB Prometheus.

**Cluster-to-cluster mode** — миграция всех тенантов между кластерами VictoriaMetrics за один запуск (`--vm-intercluster`).

## Базовые концепции

### Режимы импорта

| Режим | Подкоманда | Откуда | Тип | Скорость |
| :--- | :--- | :--- | :--- | :--- |
| `prometheus` | `vmctl prometheus` | Снапшот TSDB Prometheus (`--prom-snapshot`) | PromQL-данные, перекодировка | средняя |
| `influxdb` | `vmctl influx` | InfluxDB v1 (через `SHOW` запросы) | перекодировка | средняя |
| `opentsdb` | `vmctl opentsdb` | OpenTSDB HTTP API | перекодировка | средняя |
| `remote-read` | `vmctl remote-read` | Cortex, Mimir, Promscale, Thanos (через Remote Read API) | перекодировка | ниже |
| `thanos` | `vmctl thanos` | Thanos snapshot (локальные блоки HBase) | чтение блоков | высокая |
| `victoriametrics` | `vmctl vm-native` | source VM (single/cluster) | **native, без перекодировки** | высокая |

### Как работает native-режим

```
source VM ── /api/v1/export/native ──► vmctl ✔ контроль размеров блока
   └─────► /api/v1/import/native ◄──── vmctl ──► dst VM
```

- Данные копируются по выбранным временным диапазонам с разбиением на шаги (`--vm-native-step-interval`); при ошибке сегмента — ретраи с экспоненциальной задержкой.
- Поддерживает миграцию в cluster (`--vm-native-dst-addr` + `--vm-account-id` для single→cluster) и межкластерную миграцию (`--vm-intercluster`).
- Минус: требует доступности обоих серверов в момент миграции; блоки на приёмнике не переиндексируются заново.
- При миграции данных с перекрывающимися временными диапазонами или нестабильной сети рекомендуется включить дедупликацию на приёмнике: `-dedup.minScrapeInterval=1ms`.

### Как работает Prometheus remote-read режим

```
Prometheus/Thanos/Mimir ── Prometheus Remote Read API ──► vmctl ──► /api/v1/write ──► dst VM
```

- Данные вычитываются по стандартному Prometheus Remote Read API (query API), поэтому vmctl выступает посредником и перекодирует данные.
- Можно использовать `SAMPLES` (по умолчанию) или `STREAMED_XOR_CHUNKS` режим (`--remote-read-use-stream`), второй эффективнее для источника.
- Поддерживает фильтрацию по времени (`--remote-read-filter-time-start`/`--remote-read-filter-time-end`), меткам (`--remote-read-filter-label`/`--remote-read-filter-label-value`, можно указывать несколько раз) и разбивку на шаги (`--remote-read-step-interval`).

## Установка и настройка

### Скачивание vmctl

vmctl поставляется как часть пакета `vmutils` в релизах VictoriaMetrics:

```bash
# Linux amd64
wget https://github.com/VictoriaMetrics/VictoriaMetrics/releases/download/v1.154.0/vmutils-linux-amd64-v1.154.0.tar.gz
tar xzf vmutils-linux-amd64-v1.154.0.tar.gz
chmod +x vmctl-prod

# macOS arm64
wget https://github.com/VictoriaMetrics/VictoriaMetrics/releases/download/v1.154.0/vmutils-darwin-arm64-v1.154.0.tar.gz
tar xzf vmutils-darwin-arm64-v1.154.0.tar.gz
chmod +x vmctl-prod
```

**Docker:**
```bash
docker run --rm -it victoriametrics/vmctl:v1.154.0 vmctl --help
```

### Список доступных режимов

```bash
vmctl --help
# → opentsdb, influx, remote-read, prometheus, mimir, thanos, vm-native, verify-block
```

### Требования и предпосылки

- **Доступность:** vmctl должен иметь сетевой доступ как к источнику, так и к назначению.
- **vmctl → VictoriaMetrics:** vmctl проверяет эндпоинт `/health` на `--vm-addr` перед началом. Для cluster-режима указывайте `vminsert` адрес (`http://<vminsert>:8480`) и флаг `--vm-account-id`.
- **Prometheus snapshot:** снапшот должен быть доступен в файловой системе того хоста, где запущен vmctl.
- **Thanos/Cluster-to-cluster:** для Thanos остановите Compactor перед копированием блоков (он не потокобезопасен); для кластер-to-кластера используйте `--vm-intercluster`.

## Практические сценарии

### 1. Prometheus → VictoriaMetrics из снапшота TSDB

```bash
# 0. Создать снапшот в Prometheus (без остановки)
curl -XPOST http://prometheus:9090/api/v1/admin/tsdb/snapshot
# → {"status":"success","data":{"name":"20260922T120000Z-<sha>"}}
# Снапшот доступен по пути: /prometheus/snapshots/20260922T120000Z-<sha>/

vmctl prometheus \
  --prom-snapshot=/prometheus/snapshots/20260922T120000Z-<sha> \
  --vm-addr=http://localhost:8428/api/v1/write \
  --vm-concurrency=4 \
  --vm-backoff-retries=10
```

**Фильтрация по времени и меткам:**
```bash
vmctl prometheus \
  --prom-snapshot=/prometheus/snapshots/20260922T120000Z-<sha> \
  --prom-filter-time-start=2026-09-01T00:00:00Z \
  --prom-filter-time-end=2026-09-15T00:00:00Z \
  --prom-filter-label=__name__ \
  --prom-filter-label-value="http_.*" \
  --vm-addr=http://localhost:8428/api/v1/write \
  -s
```

- `--prom-concurrency` — число одновременных читателей снапшота (рекомендуется равно числу CPU-ядер vmctl).
- `-s` — silent mode (отключает подтверждение).
- `--vm-batch-size` (по умолчанию 200000) — количество samples в одном запросе импорта; предпочтительно 50k–500k для больших миграций.

### 2. Thanos → VictoriaMetrics (snapshot mode)

**Важно:** перед копированием остановите Thanos Compactor — он не потокобезопасен и может модифицировать блоки во время копирования.

```bash
# 1. Скопировать блоки из object storage на локальную ФС
mc cp -r minio/prometheus thanos-data

# 2. Импортировать
vmctl thanos \
  --thanos-snapshot=thanos-data \
  --vm-addr=http://victoria-metrics:8428
```

Поддерживаются как raw-блоки (resolution=0), так и downsampled блоки (5m/1h) с агрегатами `count`, `sum`, `min`, `max`, `counter`. Фильтр агрегатов:
```bash
vmctl thanos \
  --thanos-snapshot=thanos-data \
  --vm-addr=http://victoria-metrics:8428 \
  --thanos-aggr-types=count \
  --thanos-aggr-types=sum
```

### 3. Mimir / Cortex → VictoriaMetrics (remote read)

```bash
vmctl remote-read \
  --remote-read-src-addr=http://mimir:9009/prometheus \
  --remote-read-filter-time-start=2026-01-01T00:00:00Z \
  --remote-read-step-interval=day \
  --vm-addr=http://localhost:8428/api/v1/write \
  -s
```

Для Mimir/Thanos без streaming remote read рекомендуется использовать прокси `thanos-remote-read` для эффективного доступа через gRPC Store API.

### 4. VictoriaMetrics → VictoriaMetrics (vm-native mode, рекомендуется)

```bash
vmctl vm-native \
  --vm-native-src-addr=http://source-vm:8428 \
  --vm-native-dst-addr=http://dest-vm:8428 \
  --vm-native-filter-match='{__name__!~"vm_.*"}' \
  --vm-native-filter-time-start=2026-09-01T00:00:00Z \
  --vm-native-step-interval=month
```

**URL-форматы для разных сценариев:**
```bash
# single → single
--vm-native-src-addr=http://<src-vmsingle>:8428
--vm-native-dst-addr=http://<dst-vmsingle>:8428

# single → cluster (tenant 0:0)
--vm-native-src-addr=http://<src-vmsingle>:8428
--vm-native-dst-addr=http://<dst-vminsert>:8480/insert/0/prometheus

# cluster → single
--vm-native-src-addr=http://<src-vmselect>:8481/select/0/prometheus
--vm-native-dst-addr=http://<dst-vmsingle>:8428

# cluster → cluster (конкретный тенант)
--vm-native-src-addr=http://<src-vmselect>:8481/select/0/prometheus
--vm-native-dst-addr=http://<dst-vminsert>:8480/insert/0/prometheus
```

**Флаги native-режима:**
- `--vm-native-step-interval` — разбиение на интервалы: `month`, `week`, `day`, `hour`, `minute` (по умолчанию `month`). Требует `--vm-native-filter-time-start`.
- `--vm-native-filter-match` — селектор временных рядов (по умолчанию `{__name__!=""}`).
- `--vm-native-filter-time-start`/`--vm-native-filter-time-end` — временной диапазон (RFC3339).
- `--vm-native-disable-binary-protocol` — использовать JSON export вместо binary (для удаления tenant-лейблов при экспорте из cluster).
- `--vm-native-disable-http-keep-alive` — отключить persistent соединения (при ошибках `use of closed network connection`).
- `--vm-native-disable-per-metric-migration` — мигриция всех данных одним запросом вместо per-metric (меньше запросов, но без progress bar и retry).
- `--vm-native-src-headers`/`--vm-native-dst-headers` — кастомные HTTP-заголовки.
- `--vm-intercluster` — межкластерная миграция со всеми тенантами за один запуск.
- `--vm-native-backoff-retries`/`--vm-native-backoff-factor`/`--vm-native-backoff-min-duration` — параметры экспоненциального back-off.

### 5. Cluster-to-cluster (все тенанты)

```bash
vmctl vm-native \
  --vm-native-src-addr=http://vmselect:8481/ \
  --vm-native-dst-addr=http://vminsert:8480/ \
  --vm-native-filter-match='{__name__!~"vm_.*"}' \
  --vm-native-filter-time-start=2026-01-01T00:00:00Z \
  --vm-native-step-interval=day \
  --vm-intercluster \
  -s
```

`--vm-intercluster` использует `/admin/tenants` endpoint для авто-обнаружения тенантов на source.

### 6. InfluxDB → VictoriaMetrics

```bash
vmctl influx \
  --influx-addr=http://influxdb:8086 \
  --influx-database=metrics \
  --influx-user=user \
  --influx-password=$INFLUX_PASSWORD \
  --vm-addr=http://localhost:8428/api/v1/write
```

Маппинг данных InfluxDB → VictoriaMetrics:
- **Field values** → значения временных рядов
- **Tags** → лейблы (как есть)
- **Field name** → имя метрики с префиксом `{measurement}_{separator}{field}` (separator по умолчанию `_`, можно менять через `--influx-measurement-field-separator`)
- **Database name** → лейбл `db` (можно отключить `--influx-skip-database-label`)

InfluxDB v2.x не поддерживается напрямую — используйте 3rd-party решения или сначала мигрируйте в v1-совместимый режим.

## Операции и команды

### Общие флаги (для всех режимов)

| Флаг | Описание | По умолчанию |
| :--- | :--- | :--- |
| `-s` | Silent mode (без подтверждения) | `false` |
| `--verbose` | Подробные логи | `false` |
| `--disable-progress-bar` | Отключить progress bar | `false` |
| `--pushmetrics.url` | URL для push внутренних метрик vmctl | — |
| `--pushmetrics.interval` | Интервал push метрик | `10s` |
| `--pushmetrics.extraLabel` | Дополнительные лейблы (можно несколько) | — |

### Флаги назначения (--vm-*)

| Флаг | Описание | По умолчанию |
| :--- | :--- | :--- |
| `--vm-addr` | Адрес VictoriaMetrics (`httpListenAddr` или `vminsert:8480`) | `http://localhost:8428` |
| `--vm-account-id` | AccountID (tenant) для cluster-импорта | — |
| `--vm-user` / `--vm-password` | basic auth | — |
| `--vm-bearer-token` | bearer token | — |
| `--vm-headers` | Кастомные HTTP-заголовки (разделитель `^^`) | — |
| `--vm-concurrency` | Число воркеров для импорта | `2` |
| `--vm-batch-size` | Размер батча (samples) перед отправкой | `200000` |
| `--vm-compress` | gzip-сжатие запросов импорта | `true` |
| `--vm-rate-limit` | Ограничение скорости в bytes/s | `0` (выкл) |
| `--vm-extra-label` | Добавить лейбл ко всем сериям (можно несколько) | — |
| `--vm-significant-figures` | Округление значений по значащим цифрам | `0` (выкл) |
| `--vm-round-digits` | Округление до N знаков после точки | `100` |
| `--vm-backoff-retries` / `--vm-backoff-factor` / `--vm-backoff-min-duration` | Экспоненциальный back-off | `10` / `1.8` / `2s` |

### Флаги TLS

Для каждого адреса (источник/назначение) поддерживаются TLS-флаги: `--vm-cert-file`, `--vm-key-file`, `--vm-CA-file`, `--vm-server-name`, `--vm-insecure-skip-verify`.

## Мониторинг миграции

Начиная с v1.135.0 vmctl может push-ить свои внутренние метрики в VictoriaMetrics через `--pushmetrics.url`:

```bash
vmctl influx \
  --influx-addr=http://influxdb:8086 \
  --influx-database=mydb \
  --vm-addr=http://localhost:8428 \
  --pushmetrics.url=http://localhost:8428/api/v1/import/prometheus \
  --pushmetrics.extraLabel='job="vmctl"' \
  --pushmetrics.extraLabel='instance="migration-1"'
```

### Метрики vmctl

| Метрика | Описание |
| :--- | :--- |
| `vmctl_backoff_retries_total` | Число попыток retry |
| `vmctl_limiter_bytes_processed_total` | Байты через rate limiter |
| `vmctl_limiter_throttle_events_total` | События ограничения скорости |
| `vmctl_prometheus_migration_*` | Метрики prometheus-режима (blocks, series, errors) |
| `vmctl_influx_migration_*` | Метрики influx-режима (series, errors) |
| `vmctl_vm_native_migration_*` | Метрики vm-native режима (metrics, requests, tenants, bytes, errors) |

### Примеры запросов для мониторинга

```bash
# Процент завершения (influx)
vmctl_influx_migration_series_processed / vmctl_influx_migration_series_total * 100

# Процент завершения (vm-native)
vmctl_vm_native_migration_metrics_processed / vmctl_vm_native_migration_metrics_total * 100

# Скорость трансфера данных (MiB/s)
rate(vmctl_vm_native_migration_bytes_transferred_total[5m]) / 1Mi

# Частота retry
rate(vmctl_backoff_retries_total[5m])
```

### verify-block

Проверка экспортированных блоков на целостность перед загрузкой:
```bash
# Экспорт native-блока
curl -sG 'http://localhost:8428/api/v1/export/native' \
  --data-urlencode 'match[]={__name__!=""}' \
  -o exported_data_block

# Проверка
./vmctl-prod verify-block exported_data_block
# → successfully verified block, blockCount=123786
```

## Валидация установки

```bash
# Версия
vmctl --version
# → vmctl v1.154.0 ...

# Проверка достижимости источников и прав
vmctl prometheus --prom-snapshot=/path/not/exists   # ошибка сразу

# Проверка доступности VictoriaMetrics
curl -s http://localhost:8428/health
# → {}

# Проверка записи тестовой метрики
curl -s -X POST \
  -H "Content-Type: application/json" \
  --data-binary '{"metric":{"__name__":"test_metric","job":"validation"},"values":[1],"timestamps":[1234567890000]}' \
  http://localhost:8428/api/v1/import
# → HTTP/1.1 204 No Content

# Проверка появления данных
curl -s 'http://localhost:8428/api/v1/query?query=test_metric' | jq .
# → {"status":"success","data":{"resultType":"vector","result":[{"metric":{"__name__":"test_metric","job":"validation"},"value":[1234567890,"1"]}]}}

# Проверка счётчика серий на приёмнике
curl -s 'http://localhost:8428/api/v1/query?query=count({__name__=~".*"})' | jq .
```

## Поиск и устранение неисправностей

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| `write timeout` на приёмнике | `-remoteWrite.queues`/`-maxInsertRequestSize` истекают | Уменьшить `--vm-batch-size`/concurrency, увеличить таймауты VM |
| Медленный импорт из Prometheus | Перекодировка блоков, большое число серий | Использовать native-режим, увеличить `--prom-concurrency` |
| `idle duration` в статистике высокий | Источник медленно отдаёт данные или `--vm-concurrency` слишком велик | Увеличить `--<mode>-concurrency` или уменьшить `--vm-concurrency` |
| Пропущенные старые точки | Приёмник режет данные старше retention | Временно увеличить retention или писать в другой тенант |
| Дубликаты метрик после миграции | Одинаковые серии из перекрывающихся диапазонов | Включить `-dedup.minScrapeInterval=1ms` на приёмнике |
| `the number of matching timeseries exceeds...` | Превышен лимит `-search.maxSeries` на vmselect | Увеличить `-search.maxSeries` на src или сузить фильтры |
| `snapshot not found` (vmbackup) | Снапшот удалён раньше, чем скопирован | Не удалять снапшоты руками; настроить авто-удаление старых |
| Данные не мигрируют в cluster | Не указан `--vm-account-id` или неверный `vminsert` адрес | Указать `--vm-account-id` и адрес `vminsert:8480` |
| `use of closed network connection` (vm-native) | HTTP keep-alive оборван сервером | Добавить `--vm-native-disable-http-keep-alive` |
| Ошибка авторизации S3 (vmbackup) | Неверные ключи/регион/эндпоинт | Проверить `-s3.endpoint`, права bucket |
| Ошибки связи vmctl ↔ Mimir/Thanos | Таймаут remote-read (`--remote-read-http-timeout`) | Увеличить `--remote-read-http-timeout` (по умолчанию `5m`) |

## Рекомендации по эксплуатации

### Перед миграцией

- **Пилот на тестовом диапазоне:** запустите миграцию на небольшом временном диапазоне (`--vm-native-filter-time-*`) и сверьте кардинальность (`series`) на источнике и приёмнике.
- **Проверьте ресурсы приёмника:** CPU и диск — при конверсии non-native режима нагрузка на CPU выше; следите за `vm_rows_inserted_total`.
- **Настройте дедупликацию** на приёмнике (`-dedup.minScrapeInterval=1ms`), если миграция покрывает перекрывающиеся временные диапазоны или выполняется «на живую».
- **Оцените объём данных** через официальную формулу (см. [overview.md: планирование мощностей](./overview.md#планирование-мощностей-capacity-planning)).

### Непрерывный перенос «на живую»

Для непрерывного переноса данных без простоя:
1. Перенесите историю через vmctl (native или remote-read).
2. Переключите vmagent/Prometheus на новый VM с `remote_write`.
3. Используйте overlapping retention и дедупликацию на приёмнике, чтобы избежать дублей.

### Мониторинг

- Используйте `--pushmetrics.url` для push-а метрик vmctl в VictoriaMetrics.
- Следите за `vmctl_*_migration_*` метриками: процент выполнения, скорость, количество retries.
- На приёмнике мониторьте `vm_rows_inserted_total`, `vm_free_disk_space_bytes`, `vm_slow_queries_total`.

### Очистка и откат

- После миграции удалите старые снапшоты: `DELETE /snapshot/<name>` на VictoriaMetrics или `rm` снапшоты Prometheus.
- vmctl не используется для постоянной репликации — это одноразовый перенос истории.
- vmbackup/vmrestore используются для регулярного бэкапа, а не vmctl.

## Ограничения и особые случаи

- **Native-режим** не переносит между разными мажорными версиями формата хранения — совместимость версий проверяйте заранее.
- **InfluxDB v2.x** не поддерживается напрямую.
- **vmctl** — не система постоянной репликации; только перенос исторических данных.
- **Thanos Compactor** должен быть остановлен перед копированием блоков (не потокобезопасен).
- **Shared-Nothing:** vmctl не использует NFS/CIFS как `-storageDataPath` — только для резервных копий через `fs://` префикс.
- При миграции из VM cluster на single-node экспорт добавляет лейблы `vm_account_id`/`vm_project_id`; используйте `--vm-native-disable-binary-protocol` для удаления.

## Дополнительная информация

### См. также

- [VictoriaMetrics: обзор](./overview.md) — компоненты, архитектура, флаги;
- [vmbackup/vmrestore](./vmbackup_restore.md) — регулярное резервное копирование;
- [Prometheus: TSDB и снапшоты](../Prometheus/concepts/tsdb.md) — внутреннее устройство и снапшоты;
- [VictoriaMetrics: HTTP API](./http_api_reference.md) — `/api/v1/export/native`, `/api/v1/import/native`, `/snapshot/create`;
- [Официальная документация vmctl](https://docs.victoriametrics.com/victoriametrics/vmctl/) — подробные флаги и сценарии миграции.
