# Внутреннее устройство VictoriaLogs: хранение и обработка данных

**Актуально для:** VictoriaLogs v1.53.x

## Определения

**VictoriaLogs** — это специализированное решение для хранения и анализа логов, входящее в экосистему VictoriaMetrics. Оно ориентировано на высокую производительность, эффективное сжатие и минимальные накладные расходы на индексацию.

**Поток (Stream)** — группа логов с идентичным набором полей потока (например, `host`, `app`, `container`). VictoriaLogs хранит логи одного потока рядом, что обеспечивает высокую степень сжатия и скорость запросов.

**Суточный раздел (Partition)** — базовая единица организации данных на диске, соответствующая одному календарному дню (UTC).

**Сегмент (Part)** — неизменяемый самодостаточный набор данных внутри раздела, доступный для поиска.

**Блок (Block)** — минимальная единица упаковки логов внутри сегмента. Содержит строки одного потока, отсортированные по времени.

## Базовые концепции

### 1. Schema-less подход

VictoriaLogs не требует предварительного описания схемы (mapping) или создания индексов.

- **Автоматическое обнаружение полей:** любые поля в JSON-записи автоматически становятся доступными для поиска.
- **Высокая кардинальность:** система оптимизирована для хранения и поиска по полям с миллионами уникальных значений (`trace_id`, `user_id`, IP-адреса) без деградации производительности индекса, характерной для Elasticsearch или Loki.

### 2. Жизненный цикл записи лога

Процесс приема данных (Ingestion Pipeline) спроектирован для обачеспечения максимальной пропускной способности и немедленной доступности данных для поиска:

1. **Прием данных:** VictoriaLogs поддерживает широкий спектр протоколов: JSON Lines (`/insert/jsonline`), Elasticsearch Bulk API (`/insert/elasticsearch`), Grafana Loki (`/insert/loki`), OpenTelemetry (`/insert/opentelemetry`), syslog (`-syslog.listenAddr.*`), Splunk HEC (`/insert/splunk`), journald (`-journald.*`), Datadog (`/insert/datadog`, `/api/v2/logs`) и другие. Полный список протоколов и настройка коллекторов описан в [Инжест логов](./victorialogs_ingestion.md).
2. **Идентификация потока:** входящие логи группируются в потоки на основе уникального набора меток (stream fields). Это обеспечивает "локальность потока" (stream locality), когда данные одного источника хранятся физически рядом, что критично для сжатия.
3. **Буферизация в памяти:** входящие строки копируются в in-memory буферы (на короткое время, до ~1 секунды). **WAL (Write-Ahead Log) у VictoriaLogs нет** — устойчивость к сбоям обеспечивается периодическим сбросом буферов на диск через флаг `-inmemoryDataFlushInterval` (по умолчанию `5s`, минимум `1s`). Данные, не успевшие попасть в очередной сброс, теряются при нечистом завершении (OOM, `kill -9`, отключение питания).
4. **Структурирование по потокам:** логи группируются в блоки внутри потоков, что обеспечивает "локальность потока" и высокую степень сжатия.
5. **Сброс на диск (Flush):** по таймеру или при заполнении буфера данные превращаются в неизменяемые parts и записываются в суточные разделы `partitions/YYYYMMDD`; затем происходит их фоновое слияние (merge).

### 3. Кластерная архитектура и масштабирование

VictoriaLogs поставляется единым бинарным файлом, который может выполнять три роли (настраивается флагами):

- **`vlinsert`**: принимает логи и распределяет их по узлам хранения. Масштабируется при нехватке скорости приёма (CPU-bound). Поддерживает тонкую настройку лимитов памяти (`-memory.allowedPercent`) и размеров входящих строк (`-insert.maxLineSizeBytes`). В v1.53.0+ при штатной остановке буферизуется и сбрасывается в `vlstorage` (флаг `-insert.drainTimeout`, по умолчанию `5s`) вместо потери данных.
- **`vlstorage`**: хранит данные и выполняет локальный поиск. Масштабируется при росте объёма данных (Disk-bound). Позволяет задавать жёсткие лимиты на дисковое пространство (`-retention.maxDiskSpaceUsageBytes`) и период хранения (`-retentionPeriod`).
- **`vlselect`**: агрегирует результаты с узлов хранения и выполняет финальную обработку LogsQL. Масштабируется при росте числа или сложности запросов (Memory/CPU-bound).

*Рекомендуется использовать **vmauth** как точку входа перед кластером для реализации мультитенантности и разграничения прав доступа. Подробнее — в [vmauth_overview.md](./vmauth_overview.md).*

### 4. Интеграция с мониторингом

#### Алертинг (Alerting)

Статистику запросов LogsQL можно использовать для генерации оповещений через связку с `vmalert`:

1. **VictoriaLogs**: выполняет запрос LogsQL.
2. **vmalert**: регулярно запрашивает данные, проверяет условия (например, число ошибок > 10) и отправляет алерт в Alertmanager.
3. **Alertmanager**: маршрутизирует уведомления в Slack, PagerDuty или почту.

Подробнее — в [vmalert_overview.md](./vmalert_overview.md).

#### Логи в метрики (Log-to-Metrics)

Правила записи (`recording rules`) позволяют превращать результаты агрегации логов в метрики временных рядов:

- результаты LogsQL регулярно сохраняются в VictoriaMetrics (Metrics Database).
- это позволяет строить долгосрочные тренды, дашборды в Grafana и планировать мощности без необходимости хранить все исходные логи бесконечно.

## Организация хранения

### 1. Иерархия данных

VictoriaLogs использует иерархическую структуру хранения, оптимизированную для быстрого поиска и эффективной ротации данных.

#### Суточные разделы

Данные разбиты по дням в каталоге `partitions/YYYYMMDD`. Это позволяет:

- **Дешево удалять данные:** очистка по сроку хранения (`-retentionPeriod`) сводится к удалению каталогов целых дней.
- **Оптимизировать запросы:** система открывает только те разделы, которые пересекаются с временным диапазоном запроса.
- **Tiered storage:** старые разделы можно переносить между инстансами VictoriaLogs (быстрый NVMe → медленный HDD) через snapshot/transfer/restore, используя `/internal/partition/snapshot/create`, `rsync`, `/internal/partition/detach` и `/internal/partition/attach`. Подробнее в [vmbackup_restore.md](./vmbackup_restore.md).

#### Типы сегментов

- **In-memory parts:** самые свежие данные, ещё не записанные на диск.
- **Small parts:** малые сегменты на диске. Используют кэш страниц ОС для быстрого повторного чтения.
- **Big parts:** большие сегменты (до 1 ТБ), образующиеся при слиянии (merge) малых в фоновом режиме. При записи обходят кэш страниц, чтобы не вытеснять "горячие" данные.

### 2. Структура сегмента (Part)

Каждый сегмент внутри суточной партиции хранится в каталоге `datadb` и состоит из набора файлов, каждый из которых выполняет свою роль в обеспечении производительности:

| Файл | Описание |
| :--- | :--- |
| `metadata.json` | Сводная информация: число строк, блоков, временной диапазон и количество шардов. |
| `index.bin` | Заголовки всех блоков сегмента (ссылки на данные и метаданные). |
| `metaindex.bin` | Индекс поверх индекса (для быстрого позиционирования в `index.bin`). |
| `timestamps.bin` | Выделенная колонка с метками времени (`_time`) всех строк, сжатая дельта-кодированием. |
| `values.binN` | Шарды со значениями полей (кроме `_msg`). До 128 пар файлов. |
| `bloom.binN` | Фильтры Блума для соответствующих шардов значений, ускоряющие поиск токенов. |
| `message_values.bin` | Отдельное специализированное хранилище для данных основного поля сообщения `_msg`. |
| `message_bloom.bin` | Фильтр Блума специально для полнотекстового поиска в поле `_msg`. |
| `column_names.bin` | Словарь всех уникальных имен полей в сегменте с их внутренними идентификаторами. |
| `column_idxs.bin` | Карта соответствия имён полей их физическим шардам (`values.binN`). |
| `columns_header.bin` | Заголовки колонок внутри блоков (типы данных, смещения, размеры). |
| `columns_header_index.bin` | Индекс внутри заголовков колонок для быстрого перехода к нужной колонке в блоке. |

Рядом с `datadb` находится каталог `indexdb` — каталог дневного каталога потоков: перечень всех потоков, их имена полей и ссылки на данные.

#### Алгоритм фильтрации данных

1. **Проверка разделов (Partition Check):** отсечение дней, не попадающих в диапазон `_time`.
2. **Проверка метаданных (Metadata Check):** проверка пересечения временного диапазона запроса с `MinTimestamp`/`MaxTimestamp` сегмента (из `metadata.json`).
3. **Использование индексов (Metaindex & Index):** поиск блоков, соответствующих фильтрам по потокам и времени, через `metaindex.bin` → `index.bin`.
4. **Фильтр Блума (Bloom Filter):** проверка наличия искомых слов в нужных колонках блока без их распаковки (через `bloom.binN`/`message_bloom.bin`).
5. **Чтение данных (Column Reading):** точечное чтение байтов из `values.binN` только для блоков, прошедших все уровни фильтрации.

## Требования к окружению

### Операционная система

VictoriaLogs поддерживает Linux (Debian, Ubuntu, RHEL, Rocky Linux, Alpine) на архитектурах amd64 и arm64, а также macOS (amd64). Для production-эксплуатации на bare-metal рекомендуется:

- **Ядро Linux:** версия 4.14+ (для эффективной работы с диском и `io_uring`)
- **Файловая система:** ext4 или XFS (с отключением `atime` для снижения нагрузки на диск)
- **SELinux/AppArmor:** режим permissive или disabled, если не требуется корпоративная политика безопасности

### Аппаратные требования

Характер потребления ресурсов напрямую зависит от внутренней архитектуры VictoriaLogs (in-memory буферы, columnar storage, merge):

| Сценарий | CPU | RAM | Диск | Пропускная способность |
| :--- | :--- | :--- | :--- | :--- |
| **Малая нагрузка** (< 10K строк/сек) | 2 ядра | 4 GB | 50 GB SSD | 10 MB/s |
| **Средняя нагрузка** (10K–100K строк/сек) | 4–8 ядер | 8–16 GB | 200 GB SSD | 50 MB/s |
| **Высокая нагрузка** (> 100K строк/сек) | 8+ ядер | 16+ GB | 500 GB+ NVMe | 100+ MB/s |

**Важно для эксплуатации:**

- **RAM:** определяет размер кэшей и in-memory буферов недавних логов. При нехватке памяти данные сбрасываются на диск чаще, что снижает производительность ingest. Настраивается через `-memory.allowedPercent` (по умолчанию 60% от общей памяти). Официальная рекомендация — оставлять ~50% RAM свободными.
- **Диск:** требует высокой скорости случайных чтений (запросы по columnar storage) и последовательных записей (сброс in-memory буферов в `partitions`). Для production — NVMe или SSD. HDD допустим только для tiered storage (архив).
- **CPU:** фоновые операции merge (слияние малых parts в большие) и сжатие колонок потребляют CPU. При высокой нагрузке merge может конкурировать за ресурсы с ingest и запросами.

### Программные зависимости

- **Бинарный файл:** не требует внешних зависимостей. Достаточно glibc. По умолчанию данные хранятся в каталоге `victoria-logs-data` в текущей директории; путь можно изменить через `-storageDataPath`.
- **Сбор логов:** vlagent (рекомендуется), Fluent Bit, Fluentd, Promtail или любой агент, поддерживающий Elasticsearch Bulk API, Loki API, OpenTelemetry, JSON Lines или syslog.
- **Мониторинг:** `curl`, Prometheus (метрики `/metrics` отдаются на том же порту `-httpListenAddr`, по умолчанию `:9428`).
- **Бэкап:** `vmbackup`/`vmrestore` (для single-node и cluster) или snapshot через HTTP API (для single-node). Подробнее — в [vmbackup_restore.md](./vmbackup_restore.md).

### Сетевые порты

| Порт | Протокол | Назначение |
| :--- | :--- | :--- |
| `9428` | HTTP | Single-node режим: приём логов (`/insert/*`), LogsQL-запросы (`/select/logsql/*`), метрики `/metrics`, health `/health` |
| `9480` | HTTP | Cluster режим: роль `vlinsert` (приём логов). Health: `/insert/health` |
| `9481` | HTTP | Cluster режим: роль `vlselect` (запросы). Health: `/select/health` |
| `8482` | HTTP | Cluster режим: роль `vlstorage` (хранение). Health: `/health` |

---

## Установка и настройка

### Деплой на bare-metal (systemd)

**Задача:** установить VictoriaLogs на сервер без контейнеризации, с автозапуском, учетом особенностей внутреннего хранилища.

```bash
# Создание пользователя и директорий
sudo useradd --system --no-create-home --shell /usr/sbin/nologin victorialogs
sudo mkdir -p /etc/victorialogs /var/lib/victorialogs
sudo chown victorialogs:victorialogs /var/lib/victorialogs
sudo chmod 750 /var/lib/victorialogs
```

```ini
# /etc/systemd/system/victorialogs.service
[Unit]
Description=VictoriaLogs
After=network.target

[Service]
Type=simple
User=victorialogs
Group=victorialogs
ExecStart=/usr/local/bin/victoria-logs \
  -storageDataPath=/var/lib/victorialogs \
  -httpListenAddr=:9428 \
  -retentionPeriod=30d \
  -retention.maxDiskSpaceUsageBytes=100GiB \
  -memory.allowedPercent=40 \
  -inmemoryDataFlushInterval=5s
Restart=on-failure
RestartSec=5
LimitNOFILE=65536

[Install]
WantedBy=multi-user.target
```

```bash
# Установка и запуск
sudo systemctl daemon-reload
sudo systemctl enable --now victorialogs

# Проверка
systemctl status victorialogs
# → active (running)

curl -s http://localhost:9428/health
# → OK
```

**Пояснение ключевых флагов (в контексте внутреннего устройства):**

- `-storageDataPath`: корневая директория, содержащая `partitions/` (суточные разделы), `snapshots/` (снапшоты для бэкапов) и служебные каталоги. По умолчанию `victoria-logs-data`.
- `-retentionPeriod`: автоматическое удаление суточных разделов (`partitions/YYYYMMDD`), старше указанного периода. Диапазон значений: `1d`–`100y`.
- `-retention.maxDiskSpaceUsageBytes`: жёсткий лимит дискового пространства. При достижении удаляются самые старые разделы независимо от `retentionPeriod`. Приоритет выше, чем у `retentionPeriod`.
- `-retention.maxDiskUsagePercent`: динамический лимит в % от ёмкости ФС. Взаимно эксклюзивен с `maxDiskSpaceUsageBytes`.
- `-memory.allowedPercent`: процент от общего объёма RAM, разрешенный для кэшей и in-memory буферов. По умолчанию 60%. При высокой нагрузке уместно 40–50%, если важнее отдавать память под кэши ОС.
- `-inmemoryDataFlushInterval`: интервал гарантированного сброса in-memory данных на диск (минимум `1s`, по умолчанию `5s`). Меньшее значение = меньшая потеря данных при сбое, но большее число операций записи. Данные, не успевшие попасть в сброс, теряются при нечистом завершении (OOM, `kill -9`, отключение питания).
- `-storage.minFreeDiskSpaceBytes`: минимум свободного места на диске. При достижении хранилище переходит в режим read-only. По умолчанию 100 MB.
- `-insert.maxLineSizeBytes`: максимальный размер одной строки при приёме (по умолчанию `256KiB`). Строки длиннее лимита отклоняются.
- `-insert.drainTimeout`: время ожидания сброса буферов в `vlstorage` при штатной остановке в cluster-режиме (v1.53.0+, по умолчанию `5s`).

**Особенности первого запуска:**

- при первом запуске VictoriaLogs создаёт структуру каталогов (`partitions/`, `snapshots/`) в `-storageDataPath`.
- при последующих запусках данные читаются напрямую из `partitions/` — replay отсутствует (нет WAL), поэтому старт не зависит от объёма «недописанных» данных.
- последние до `-inmemoryDataFlushInterval` секунд данных, не сброшенных на диск, теряются при аварийном завершении.

### Запуск в Docker

```bash
docker run -d \
  --name victorialogs \
  --cpus=2 \
  --memory=4g \
  --ulimit nofile=65536:65536 \
  -p 9428:9428 \
  -v /etc/victorialogs:/storage \
  victoriametrics/victoria-logs:v1.53.0 \
  -storageDataPath=/storage
```

### Кластерный режим

В cluster-режиме VictoriaLogs разворачивается как три независимые роли:

| Роль | Бинарник | Порт | Health endpoint |
| :--- | :--- | :--- | :--- |
| `vlinsert` | `victoria-logs` | 9480 | `/insert/health` → `ok` |
| `vlselect` | `victoria-logs` | 9481 | `/select/health` → `ok` |
| `vlstorage` | `victoria-logs` | 8482 | `/health` → `OK` |

`vlinsert` принимает логи и распределяет их по `vlstorage` узлам. `vlselect` агрегирует результаты. Рекомендуется использовать **vmauth** перед кластером для мультитенантности. Подробнее — в [victorialogs_k8s_setup.md](../Kubernetes/MonitoringLogging/victorialogs_k8s_setup.md).

### Resource Limits и тюнинг производительности

**Ограничение через systemd:**

```ini
# /etc/systemd/system/victorialogs.service
[Service]
CPUQuota=50%
MemoryMax=4G
TasksMax=128
LimitNOFILE=200000
```

**Тюнинг параметров (влияние на внутренние механизмы):**

| Параметр | Влияние | Рекомендация |
| :--- | :--- | :--- |
| `-memory.allowedPercent` | Размер кэшей и in-memory буферов | По умолчанию 60% RAM. 30–50%, если нужен запас памяти под кэш ОС. Выше → быстрее ingest, но риск OOM |
| `-inmemoryDataFlushInterval` | Интервал сброса буферов на диск | По умолчанию `5s` (минимум `1s`). Меньше → меньше данных теряется при аварийном завершении, но больше I/O |
| `-storage.minFreeDiskSpaceBytes` | Порог свободного места, после которого хранилище → read-only | По умолчанию 100 MB. Ставьте 5–10% от объёма диска |
| `-insert.maxLineSizeBytes` | Максимальный размер одной строки | По умолчанию `256KiB`. Увеличьте для больших событий; строки длиннее лимита отклоняются |
| `-insert.maxLineSizeBytes` | Максимальное число полей в строке | По умолчанию неограниченно. Ограничьте для защиты от «wide events» с множеством полей |
| `-insert.concurrency` | Число параллельных запросов приёма на каждый `vlstorage` | По умолчанию 2 |
| `-insert.drainTimeout` | Время ожидания сброса буферов при graceful shutdown (cluster) | По умолчанию `5s` (v1.53.0+) |
| `-insert.maxQueueDuration` | Время ожидания в очереди приёма | По умолчанию `1m0s` |
| `-search.maxQueryDuration` | Таймаут запросов | По умолчанию `30s`, переопределяется `timeout` в запросе |
| `-search.maxConcurrentRequests` | Лимит одновременных запросов | По умолчанию `2×CPU` при ≤4 ядрах, иначе `CPU`, максимум `16` |
| `-snapshotsMaxAge` | Автоудаление старых снапшотов партиций | По умолчанию `3d` |

**Рекомендации по нагрузке:**

- **<10K строк/сек:** параметры по умолчанию, `LimitNOFILE=65536`, `memory.allowedPercent=60`
- **10K–100K строк/сек:** `memory.allowedPercent=40-50%`, `LimitNOFILE=100000`, NVMe для `-storageDataPath`
- **>100K строк/сек:** выделенный NVMe под `-storageDataPath`, `defaultParallelReaders` по числу ядер, `search.maxConcurrentRequests=16`, 8+ ядер CPU

## Операции и команды

### Валидация установки

**Health checks:**

```bash
# Проверка доступности HTTP-эндпоинта
curl -s http://localhost:9428/health
# → OK

# Проверка метрик самомониторинга
curl -s http://localhost:9428/metrics | grep -E '^vl_(rows_ingested_total|pending_rows|storage_parts)'
# → vl_rows_ingested_total{type="jsonline"} 123
# → vl_pending_rows{type="storage"} 0
# → vl_storage_parts{type="storage/inmemory"} 1
```

**Верификация внутреннего состояния:**

```bash
# Проверить, что сервис стартовал (в логах)
journalctl -u victorialogs --since "5 min ago" --no-pager | grep -iE "started|http server"
# → ... VictoriaLogs started successfully

# Проверить загрузку разделов
ls -la /var/lib/victorialogs/partitions/
# → 20240101  20240102  ...

# Проверить список активных разделов через HTTP API
curl -s http://localhost:9428/internal/partition/list | jq
# → [{"name":"20240101"}, ...]

# Принудительный flush in-memory буферов на диск (v1.53.0+ — POST)
curl -X POST http://localhost:9428/internal/force_flush
# → flushed

# Принудительный merge для конкретного раздела (v1.53.0+ — POST)
curl -X POST 'http://localhost:9428/internal/force_merge?partition_prefix=20240101'
```

**Верификация данных:**

```bash
# Отправить тестовый лог
echo '{"level":"info","msg":"health check"}' | \
  curl -X POST http://localhost:9428/insert/jsonline -d @-

# Проверить, что лог появился
curl -s 'http://localhost:9428/select/logsql/query' \
  --data-urlencode 'query=_time:5m | stats count()'
# → count(): 1
```

**Диагностика типичных проблем:**

| Симптом | Возможная причина | Решение |
| :--- | :--- | :--- |
| `/health` не отвечает | Сервис не запущен | `systemctl status victorialogs` |
| Нет метрик `vl_*` | Сервис не стартовал или firewall | Проверить логи `journalctl -u victorialogs` |
| Нет данных после ingest | in-memory буфер ещё не сброшен | Подождать до 5 секунд или выполнить `POST /internal/force_flush` |
| Нет данных после ingest в cluster | `vlinsert` не видит `vlstorage` | Проверить `-storageNode`, порт `-httpListenAddr` и сетевую доступность |
| Ошибка открытия файлов | `LimitNOFILE` слишком мал | Увеличить `LimitNOFILE` до 100000+ |

## Управление хранением и retention

### Ручное управление разделами

```bash
# Просмотр разделов
ls -la /var/lib/victorialogs/partitions/

# Проверка размера разделов
du -sh /var/lib/victorialogs/partitions/* | sort -rh | head

# Просмотр метаданных раздела
cat /var/lib/victorialogs/partitions/20240101/metadata.json

# Просмотр списка активных партиций
curl -s http://localhost:9428/internal/partition/list | jq
```

```bash
# Принудительное удаление старого раздела (например, при изменении retention)
# ВАЖНО: сервис должен быть остановлен
sudo systemctl stop victorialogs
sudo rm -rf /var/lib/victorialogs/partitions/20240101
sudo systemctl start victorialogs
```

### Управление снапшотами

```bash
# Список созданных снапшотов
curl -X POST http://localhost:9428/internal/partition/snapshot/list | jq

# Создание снапшота для конкретного раздела (v1.53.0+ — POST)
curl -X POST 'http://localhost:9428/internal/partition/snapshot/create?partition_prefix=20240101' | jq

# Создание снапшота для всех разделов (v1.53.0+ — POST)
curl -X POST 'http://localhost:9428/internal/partition/snapshot/create' | jq
# → ["/var/lib/victorialogs/snapshots/2026-10-16T10-00-00/..."]

# Автоочистка старых снапшотов через флаг (по умолчанию 3d)
# -snapshotsMaxAge=3d

# Ручное удаление конкретного снапшота (v1.53.0+ — POST)
curl -X POST 'http://localhost:9428/internal/partition/snapshot/delete?path=<snapshot-path>'

# Автоочистка снапшотов старше N (v1.53.0+ — POST)
curl -X POST 'http://localhost:9428/internal/partition/snapshot/delete_stale?max_age=7d'
```

**Поведение retention:**

- `-retentionPeriod`: «мягкий» лимит. Фоновая очистка удаляет разделы старше указанного периода (по умолчанию 7 дней, диапазон `1d`–`100y`).
- `-retention.maxDiskSpaceUsageBytes`: «жёсткий» лимит. При достижении удаляются самые старые разделы независимо от `retentionPeriod`.
- `-retention.maxDiskUsagePercent`: динамический лимит в %. Взаимно эксклюзивен с `maxDiskSpaceUsageBytes`.
- Приоритет: `maxDiskSpaceUsageBytes`/`maxDiskUsagePercent` > `retentionPeriod`.

### Восстановление после заполнения диска

```bash
# 1. Временно увеличить лимит или отключить strict limit
# 2. Удалить самый старый раздел
sudo rm -rf /var/lib/victorialogs/partitions/20230101
# 3. Перезапустить сервис
sudo systemctl restart victorialogs
```

VictoriaLogs переходит в режим **read-only** при недостатке диска (`-storage.minFreeDiskSpaceBytes`). Проверить метрикой `vl_storage_is_read_only=1`.

## Безопасность

### Права доступа к файлам

```bash
# Корректные права на storage
sudo chown -R victorialogs:victorialogs /var/lib/victorialogs
sudo chmod 750 /var/lib/victorialogs

# Конфигурация
sudo chown -R victorialogs:victorialogs /etc/victorialogs
sudo chmod 750 /etc/victorialogs
```

### Шифрование данных на диске

VictoriaLogs не предоставляет встроенного шифрования (data-at-rest). Для защиты чувствительных данных используйте:

- **LUKS/dm-crypt:** шифрование всего раздела с `-storageDataPath`.
- **Файловая система с шифрованием:** eCryptfs, ZFS encryption.

### Сетевая безопасность

**Single-node:**

```bash
# Ограничение доступа к порту 9428 (только из trusted subnet)
sudo ufw deny 9428
sudo ufw allow from 10.0.0.0/8 to any port 9428

# Или через iptables
sudo iptables -A INPUT -p tcp --dport 9428 -s 10.0.0.0/8 -J ACCEPT
sudo iptables -A INPUT -p tcp --dport 9428 -J DROP
```

**Cluster mode:**

- используйте **vmauth** как точку входа для реализации мультитенантности и разграничения прав доступа (см. [vmauth_overview.md](./vmauth_overview.md)).
- включите mTLS между компонентами кластера (`-tls.keyFile`, `-tls.certFile`, `-tls.clientAuthFile`).
- используйте сетевую изоляцию между компонентами кластера (firewall-правила на хостах или NetworkPolicy в Kubernetes).

### Защита системных эндпоинтов (v1.53.0+)

Начиная с v1.53.0, внутренние эндпоинты требуют метод `POST` для предотвращения GET-based SSRF-атак. Защита через authKey:

- `-partitionManageAuthKey` — защита `/internal/partition/*`, `/internal/force_merge`, `/internal/force_flush`, `/internal/log_new_streams`
- `-forceMergeAuthKey` — защита `/internal/force_merge`
- `-logNewStreamsAuthKey` — защита `/internal/log_new_streams`
- `-deleteAuthKey` — защита `/delete/*` (включает API удаления через `-delete.enable`)

### Мультитенантность

В single-node режиме мультитенантность через HTTP-заголовки `AccountID` и `ProjectID` (32-bit unsigned, по умолчанию 0). VictoriaLogs не выполняет per-tenant авторизацию — используйте vmauth с маршрутизацией по заголовкам.

## Резервное копирование и восстановление

### Стратегия бэкапа через снапшоты партиций

```bash
# Метод 1: снапшот партиции + rsync/rclone (официальная процедура, без остановки)

# 1) Снимок всех активных партиций (или конкретной: ?partition_prefix=YYYYMMDD)
curl -X POST 'http://localhost:9428/internal/partition/snapshot/create' | jq
# → ["/var/lib/victorialogs/snapshots/2026-10-16T10-00-00/..."]

# 2) Копия снапшота на другой хост (rsync --delete) или в объектное хранилище (rclone)
rsync -av /var/lib/victorialogs/snapshots/2026-10-16T10-00-00/ remote:/backups/vl/2026-10-16/

# 3) Уборка неиспользуемых снапшотов
curl -X POST 'http://localhost:9428/internal/partition/snapshot/delete?path=<snapshot-path>'
# Или автоочистка через флаг: -snapshotsMaxAge=3d
```

Подробнее про бэкап через `vmbackup`/`vmrestore` — в [vmbackup_restore.md](./vmbackup_restore.md).

### Восстановление из снапшота

```bash
# 1. Остановить сервис
sudo systemctl stop victorialogs

# 2. Восстановить данные партиции из бэкапа
sudo rsync -a --delete /backup/vl/20240101/ /var/lib/victorialogs/partitions/20240101/

# 3. Проверить права
sudo chown -R victorialogs:victorialogs /var/lib/victorialogs
sudo chmod 750 /var/lib/victorialogs

# 4. Запустить сервис
sudo systemctl start victorialogs

# 5. Валидация
sleep 5
curl -s http://localhost:9428/health
# → OK
```

### Восстановление через partition attach/detach

```bash
# Отделить проблемную партицию, восстановить её из backup, подключить обратно
# (vlstorage должен быть запущен)

# 1. Отсоединить партицию (ждёт завершения читающих запросов)
curl -X POST 'http://localhost:9428/internal/partition/detach?name=20240101'

# 2. Скопировать данные из бэкапа
sudo rsync -a --delete /backup/vl/20240101/ /var/lib/victorialogs/partitions/20240101/

# 3. Подключить партицию обратно
curl -X POST 'http://localhost:9428/internal/partition/attach?name=20240101'
```

**Что включать в backup:**

- `/var/lib/victorialogs/partitions/` — все суточные разделы с логами
- `/etc/victorialogs/` — конфигурационные файлы
- список снапшотов через `/internal/partition/snapshot/list`

## Процедура обновления и отката

### Обновление single-node (bare-metal)

```bash
# 1. Проверить текущую версию
victoria-logs -version

# 2. Скачать новую версию
VERSION=v1.53.0
wget https://github.com/VictoriaMetrics/VictoriaLogs/releases/download/${VERSION}/victoria-logs-linux-amd64-${VERSION}.tar.gz
tar -xzf victoria-logs-linux-amd64-${VERSION}.tar.gz
# → victoria-logs-prod   (архив содержит единственный бинарник)

# 3. Создать бэкап перед обновлением
sudo tar -czf /root/vl-pre-upgrade-$(date +%F).tar.gz \
  /var/lib/victorialogs /etc/victorialogs

# 4. Остановить сервис
sudo systemctl stop victorialogs

# 5. Заменить бинарный файл
sudo cp victoria-logs-prod /usr/local/bin/victoria-logs
sudo chmod +x /usr/local/bin/victoria-logs

# 6. Запустить сервис
sudo systemctl start victorialogs

# 7. Проверить статус
systemctl status victorialogs
# → active (running)

curl -s http://localhost:9428/health
# → OK

# 8. Проверить загрузку данных
journalctl -u victorialogs --since "2 min ago" --no-pager | grep -iE "partition|started"
```

**Откат (rollback):**

```bash
# Если новая версия работает некорректно
sudo systemctl stop victorialogs

# Вариант А: вернуть предыдущий бинарник (если сохранили)
sudo cp /root/victoria-logs-old /usr/local/bin/victoria-logs
sudo chmod +x /usr/local/bin/victoria-logs

# Вариант Б: восстановить данные из backup
# sudo tar -xzf /root/vl-pre-upgrade-YYYY-MM-DD.tar.gz -C /

sudo systemctl start victorialogs

# Валидация
curl -s http://localhost:9428/health
```

**Важно:**

- формат данных на диске может меняться между мажорными версиями. перед downgrade читайте release notes; при несовместимом изменении формата требуется восстановление из backup.
- при обновлении cluster-режима: обновляйте `vlstorage` первыми, затем `vlinsert`, затем `vlselect`.

### Обновление в Docker

```bash
# 1. Остановить старый контейнер
docker stop victorialogs
docker rm victorialogs

# 2. Загрузить новый образ
docker pull victoriametrics/victoria-logs:v1.53.0

# 3. Запустить с той же конфигурацией (тома сохранены)
docker run -d \
  --name victorialogs \
  --cpus=2 \
  --memory=4g \
  -p 9428:9428 \
  -v /etc/victorialogs:/storage \
  victoriametrics/victoria-logs:v1.53.0 \
  -storageDataPath=/storage
```

**Проверка после обновления:**

```bash
# Проверка версии
victoria-logs -version
# → victoria-logs version v1.53.0

# Проверка partitions
curl -s 'http://localhost:9428/select/logsql/query' \
  --data-urlencode 'query=_time:1h | stats count()'
# → данные возвращаются
```

## Устранение неполадок

### Типичные ошибки и диагностика

| Симптом | Возможная причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| Нет данных сразу после ingest | in-memory буфер ещё не сброшен | `journalctl -u victorialogs`; `POST /internal/force_flush` | Подождать до 5 секунд или выполнить принудительный flush |
| Диск заполнен | `-storage.minFreeDiskSpaceBytes` достигнут или `retention.maxDiskSpaceUsageBytes` | `df -h /var/lib/victorialogs` | Увеличить лимит или удалить старые partition вручную |
| Потеря логов после сбоя | Последние секунды не сброшены на диск | `journalctl -u victorialogs` | Ожидаемо при OOM/`kill -9`; снизить `-inmemoryDataFlushInterval`, при необходимости восстановить из backup |
| Высокий disk I/O | Фоновая компакция (merge) | `iotop -o` | Нормальное поведение. Проверить `-search.maxConcurrentRequests` — одновременные запросы конкурируют с merge |
| OOM при ingest | Слишком большой `memory.allowedPercent` | `dmesg \| grep -i oom` | Уменьшить `memory.allowedPercent`, увеличить RAM |
| Медленные запросы | Слишком много small parts | `ls /var/lib/victorialogs/partitions/*/datadb/` | Запустить `POST /internal/force_merge` в окно низкой нагрузки |
| Коррупция данных | Аварйное выключение, битый диск | `ls /var/lib/victorialogs/partitions/`; метрика `vl_storage_parts` | Восстановить проблемный раздел из backup (rsync + `/internal/partition/attach`) |
| `POST` required error | v1.53.0+ требует POST для `/internal/*` эндпоинтов | Ошибка в логах при вызове `GET` | Использовать `curl -X POST` вместо `GET` |

### Диагностические команды

```bash
# Проверка статуса сервиса (systemd)
systemctl status victorialogs
journalctl -u victorialogs --since "1 hour ago" --no-pager

# Проверка ресурсов
ps -p $(pgrep victoria-logs) -o pid,%cpu,%mem,cmd
cat /proc/$(pgrep victoria-logs)/limits | grep "open files"

# Проверка диска
df -h /var/lib/victorialogs
du -sh /var/lib/victorialogs/partitions/* | sort -rh | head

# Проверка снапшотов
du -sh /var/lib/victorialogs/snapshots/ 2>/dev/null
curl -X POST http://localhost:9428/internal/partition/snapshot/list | jq

# Проверка метрик
curl -s http://localhost:9428/metrics | grep '^vl_'

# Список активных partition'ов
curl -s http://localhost:9428/internal/partition/list | jq

# Проверка доступности (cluster mode)
curl -s http://vlstorage:8482/health
# → OK
```

### Восстановление после сбоя

```bash
# Сценарий 1: штатный restart — данные читаются напрямую из partitions/
sudo systemctl restart victorialogs
sleep 5
curl -s http://localhost:9428/health
# → OK

# Сценарий 2: подозрение на повреждение конкретного раздела
# Отделить раздел, восстановить его из backup, не трогая остальные данные:
curl -X POST 'http://localhost:9428/internal/partition/detach?name=20240101'
sudo rsync -a --delete /backup/vl/20240101/ /var/lib/victorialogs/partitions/20240101/
curl -X POST 'http://localhost:9428/internal/partition/attach?name=20240101'

# Сценарий 3: Полное восстановление из backup
sudo systemctl stop victorialogs
sudo tar -xzf /root/vl-backup-2024-01-01.tar.gz -C /
sudo systemctl start victorialogs
```

## Best Practices

### Производительность запросов

1. **Фильтрация по времени:** всегда ограничивайте запрос временным диапазоном (`_time:5m`), чтобы VictoriaLogs сканировал минимум разделов и сегментов.
2. **Выбор колонок:** используйте `| fields _time, host, _msg` в конце запроса. Это позволит системе не извлекать с диска данные всех полей каждой строки, а прочитать только нужные колонки.
3. **Полнотекстовый поиск:** благодаря фильтрам Блума поиск по ключевым словам в поле `_msg` выполняется очень быстро, так как система мгновенно отсекает блоки, не содержащие искомых токенов.

### Оптимизация полей потока

Поля потока (`_stream_fields`) должны быть **низкокардинальными** (стабильными): `host`, `app`, `pod`.

Высококардинальные данные (`trace_id`, `user_id`, `request_id`) следует оставлять обычными полями. Неправильный выбор полей потока приводит к созданию слишком большого числа мелких потоков (High Cardinality), что снижает эффективность сжатия и замедляет поиск.

### Capacity Planning

Исходя из официальной документации, рекомендуется оставлять следующие резервы:

- **50% свободной RAM** для снижения вероятности OOM и замедлений во время пиковых нагрузок
- **50% свободного CPU** для снижения вероятности замедлений во время пиковых нагрузок
- **не менее 20% свободного места на диске** в каталоге `-storageDataPath`

### Sudo и привилегии

- запускайте VictoriaLogs от непривилегированного пользователя (не `root`)
- ограничьте права доступа к `-storageDataPath` (750)
- используйте `LimitNOFILE` ≥ 65536 (для больших установок — 100000+)
- ограничьте сетевой доступ через firewall/ufw для single-node или NetworkPolicy для cluster

### Сжатие и экономия дискового пространства

- коэффициент сжатия columnar storage: ~10:1 для типичных JSON-логов, 5–10:1 для plain text
- используйте `-retentionPeriod` для управления сроком хранения
- используйте `-retention.maxDiskSpaceUsageBytes` или `-retention.maxDiskUsagePercent` для жёсткого лимита
- планируйте резерв ≥20% на снапшоты партиций, временные файлы компакции и рост merge

### Edge Cases и известные ограничения

- **Sequential evaluation:** LogsQL запросы выполняются последовательно по пайпам. Сложные запросы с большим количеством строк могут занимать значительное время и память.
- **Merge stalls:** при очень высокой ingest-нагрузке merge small parts в big parts может отставать. Это нормальное поведение; для устранения используйте `POST /internal/force_merge` в окно низкой нагрузки.
- **Column sharding > 128 полей:** если в сегменте более 128 уникальных полей, они циклически распределяются по шардам `values.binN`. Это не влияет на запросы, но увеличивает число открываемых файлов.
- **Big parts и page cache:** big parts (>4GB) при чтении обходят кэш страниц ОС, чтобы не вытеснять "горячее" данные. Это уменьшает cache hit ratio для больших исторических запросов, но повышает общую производительность.
- **Размер строки:** максимальный размер одной строки — 256 KiB по умолчанию (`-insert.maxLineSizeBytes`). Строки длиннее лимита отклоняются и считаются в метрике `vl_too_long_lines_skipped_total`.
- **Нет Windows-сборок:** официальные бинарники есть для Linux, macOS и FreeBSD (amd64/arm64 и др.), Windows-сборок не публикуется.
- **S3-совместимое хранилище:** для долгосрочного архива используйте `vmbackup` с S3-совместимым объектным хранилищем (MinIO, Ceph, или любой S3-compatible endpoint). Подробнее — в [vmbackup_restore.md](./vmbackup_restore.md).

## Дополнительная информация

### См. также

- **[LogsQL: язык запросов](./logsql_overview.md)** — руководство по языку запросов и аналитике.
- **[Инжест логов](./victorialogs_ingestion.md)** — протоколы приёма, HTTP API, параметры запросов и коллекторы.
- **[Обзор VictoriaMetrics](./overview.md)** — общая информация об экосистеме и сравнение с VictoriaLogs.
- **[vmbackup и vmrestore](./vmbackup_restore.md)** — резервное копирование и восстановление.
- **[vmauth: обзор](./vmauth_overview.md)** — аутентификация, multitenancy и разграничение прав.
- **[vmalert: обзор](./vmalert_overview.md)** — алертинг на основе LogsQL.
- **[Развёртывание в Kubernetes](../Kubernetes/MonitoringLogging/victorialogs_k8s_setup.md)** — VLCluster, vlagent и CRD.
