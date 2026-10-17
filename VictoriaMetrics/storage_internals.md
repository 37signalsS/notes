# Внутреннее устройство хранилища метрик (single-node / vmstorage)

**Актуально для:** VictoriaMetrics v1.154.x

## Определения

**Part / сегмент (part)** — самодостаточный файловый блок с данными одной суточной партиции: файлы данных временных рядов + индекс. Различают **small parts** (свежие, до ~1 МБ / до 8 млн строк) и **big parts** (результат слияния).

**Партиция (partition)** — каталог за одни сутки: `{storageDataPath}/data/YYYYMMDD/`. Retention работает покадрово — удаляет целую партицию.

**TSID** — компактный внутренний идентификатор временного ряда; присваивается каждой уникальной паре `metric_name+labels`. Все сэмплы ряда хранятся вместе под одним TSID, поэтому запросы «по ряду» не зависят от размера labels.

**indexdb** — инвертированный индекс `(labels → TSID)`, ротируется каждые 10 минут в каталоге `indexdb/`. От размера indexdb зависит память, потребляемая на метаданные.

**WAL (Write-Ahead Log)** — журнал предзаписи. Гарантирует, что при аварийном завершении данные не теряются: перезапуск срабатывает по WAL, не изменяя уже упакованные parts.

**merge (компакция)** — фоновое слияние малых parts в большие; снижает число файлов и ускоряет запросы, но создаёт транзиентную нагрузку на IOPS.

**Кеши (cache)** — подкаталог `{storageDataPath}/cache/` с несколькими типами кешей:

| Кеш | Размер по умолчанию | Назначение | Персистентный |
| :--- | :--- | :--- | :--- |
| `storage/tsid` | конфигурируется `-storage.cacheSizeStorageTSID` | MetricName → TSID | да (на диск) |
| `storage/metricName` | конфигурируется `-storage.cacheSizeStorageMetricName` | MetricID → MetricName | да (на диск) |
| `indexdb/indexBlocks` | 10% от RAM (`-storage.cacheSizeIndexDBIndexBlocks`) | Метаданные блоков индекса | нет |
| `indexdb/dataBlocks` | 25% от RAM (`-storage.cacheSizeIndexDBDataBlocks`) | Данные блоков индекса | нет |
| `indexdb/dataBlocksSparse` | конфигурируется | Sparse-данные блоков | нет |
| `indexdb/tagFilters` | 3% от RAM (`-storage.cacheSizeIndexDBTagFilters`) | tag filters → MetricIDs | нет |

При необходимости можно удалить кеш на старте: создайте файл `reset_cache_on_startup` в каталоге `cache/` — он будет удалён, и кеш пересоздастся заново (см. issue #1447).

## Базовые концепции

### Структура каталога данных (single-node)

```
{storageDataPath}/
├── data/
│   ├── 20260120/                 # суточная партиция
│   │   └── parts/
│   │       ├── 20260120_..._small/   # fresh small parts
│   │       └── 20260120_..._big/     # merged big parts
│   └── 20260121/
├── indexdb/                       # инвертированный индекс, ротация по 10 мин
│   └── 20260120123000000 ...
├── wal/                           # WAL + tmp
├── snapshots/                     # снапшоты для vmbackup
└── cache/                         # служебные кэши (метаданные, инверт. индексы)
```

В cluster-режиме эта структура живёт в `{storageDataPath}` каждого **vmstorage** независимо (Shared-Nothing).

### Путь сэмпла через engine

```
приём (vminsert / vmsingle /api/v1/write или remote_write)
   → буфер in-memory parts  (чтобы избежать частой записи на диск)
   → flush по -inmemoryDataFlushInterval (по умолч. 5s) в small part
   → фоновый merge: small → big (до ~4GiB) 
   → партиция покрывает ровно один день
```

- `-inmemoryDataFlushInterval` — как часто сбрасывать in-memory на диск (5s по умолчанию; при низком аптайме после сбоя увеличивает WAL-replay).
- **Финальный merge** в конце суток запускается автоматически фоновым планировщиком merge; отдельного `-finalMergeDelay` больше нет (флаг deprecated и не выполняет никакой функции).
- Частота записи: только большие сэмплы уходят напрямую в part; для высокочастотных метрик — WAL.

### Ретенция и партиции

- `-retentionPeriod` (single-node) / `<`vmstorage` флаг>` (cluster) — сколько дней держать. Удаление — целыми партициями фоном (при старте и далее раз в час).
- При коротком окне retention экономится место, но растёт merge-нагрузка на стыке партиций: выставляйте значок, кратный суткам.

## Требования и предпосылки (Prerequisites)

- **ОС:** любой современный Linux (Debian, Ubuntu, RHEL, Rocky Linux, Alpine) — kernel 4.14+ для эффективной работы с диском (`io_uring`).
- **ФС:** XFS или ext4 с `noatime,nodiratime` (или отключённым `atime`).
- **Диски:** SSD/NVMe для production; VictoriaMetrics оптимизирована для HDD, но на magnetics запросы замедляются. `-storageDataPath` — только локальный диск или RAID (не NFS/CIFS).
- **Пользователь:** создайте непривилегированного пользователя `victoriametrics` с домашним каталогом на том же разделе, что и `-storageDataPath`.
- **Лимиты:** `ulimit -n` ≥ 65535 для single-node, ≥ 200000 для cluster; в systemd — `LimitNOFILE=200000`.
- **Минимальный свободный диск:** `-storage.minFreeDiskSpaceBytes` (по умолчанию `100MB`); при достижении хранилище переходит в read-only.

## Операции и команды (Operations and Commands)

| Операция | Команда / эндпоинт | Авторизация |
| :--- | :--- | :--- |
| Force merge (компакция раздела) | `POST /internal/force_merge?partition_prefix=YYYYMMDD` | `-forceMergeAuthKey` |
| Force flush (сброс in-memory на диск) | `POST /internal/force_flush` | `-forceFlushAuthKey` |
| Создание снапшота | `POST /snapshot/create` | `-snapshotAuthKey` |
| Список снапшотов | `GET /snapshot/list` | `-snapshotAuthKey` |
| Удаление снапшота | `POST /snapshot/delete?snapshot=...` | `-snapshotAuthKey` |
| Удаление всех снапшотов | `POST /snapshot/delete_all` | `-snapshotAuthKey` |
| Сброс кэша | создать файл `reset_cache_on_startup` в `cache/` и перезапустить | — |
| Удаление серий | `POST /api/v1/admin/tsdb/delete_series?match[]={...}` (single-node: vmsingle; cluster: vmselect `/delete/<accountID>/<projectID>/prometheus/api/v1/admin/tsdb/delete_series`) | `-deleteAuthKey` |

## Практические сценарии

### 1. Оценка и контроль диска

```bash
# Структура и объёмы
du -sh /var/lib/victoria-metrics/data/*  | sort -rh | head
# →  большие части суммарно указывают на реальный объем данных

# Проверка числа parts (указывает на качество merge)
curl -s http://localhost:8428/metrics | grep -E '^vm_parts{(prefix_path=)?' | head
```

### 2. Диагностика merge и кэшей

```bash
# Сколько частей, сколько merge выполнено
curl -s http://localhost:8428/metrics | grep -E '^vm_(merges_total|parts|bg_merge)'
# Кэш индексов
curl -s http://localhost:8428/metrics | grep -E '^vm_cache_size_max_bytes_|^vm_cache_entries'
```

Переменные, влияющие на merge: `-maxConcurrentInserts`, `-concurrentInsertsMultiplier`, `-sched.*` — при низкой IOPS не занижайте параллельность merge бездумно.

### 3. Работа с retention вручную

```bash
# Просмотр партиций
ls /var/lib/victoria-metrics/data/
# Принудительное удаление старой партиции (запись остановлена)
rm -rf /var/lib/victoria-metrics/data/20250101
# → НЕ делать при работающем инстансе; лучше -retentionPeriod и файловый он-лайн cleanup
```

## Валидация установки

```bash
# Проверка, что в партициях есть данные
ls /var/lib/victoria-metrics/data/ | wc -l

# Проверка WAL: размер не должен бесконечно расти
du -sh /var/lib/victoria-metrics/wal/

# Метрики здоровья хранилища
curl -s http://localhost:8428/metrics | grep -E '^vm_(data_size_bytes|free_disk_space_bytes|rows_inserted_total)' 
```

## Оценка ресурсов (RAM и диск)

Основной потребитель RAM у `vmstorage`/single-node — **indexdb** (инвертированный индекс `labels → TSID`) и in-memory parts. Память растёт с числом **уникальных серий** (кардинальность), а не с объёмом сырых данных на диске.

- **Эмпирический ориентир:** примерно 100 тыс. – 1 млн активных серий на ~1 ГБ RAM для storage-узла (зависит от числа меток и их кардинальности). Цифра сильно варьируется — подбирайте по замерам.
- Индекс ротируется каждые 10 минут: при высокой churn (приход/уход серий) временно занято больше памяти, чем средняя кардинальность.
- Для single-node `-memory.allowedPercent` (по умолчанию 60) ограничивает долю RAM, используемую для кеша/внутренних буферов; для кластера это значение задаётся на каждом `vmstorage`.

Как оценить **до** запуска:

1. Направить репликацию vmagent в [vmestimator](./vmestimator.md) и дать потоку поработать: оценки считаются по живому входящему потоку, ретроспективно по уже накопленным данным их не получить;
2. Умножить прогноз серий на характерный объём на серию (измерьте на проде: `vm_data_size_bytes{type="indexdb/file"}` и `vm_data_size_bytes{type="storage/big"}` — footprints индекса и данных). Дополнительная диагностика — метрики `vm_indexdb_cache_entries`, `vm_indexdb_cache_size_max_bytes`, `vm_cache_misses_total{type="indexdb/dataBlocks"}`.
3. Заложить запас ×2 на churn и рост; отдельно — RAM под ОС и конфиг (не считайте 100% на VM).

Диагностика фактического потребления: `/api/v1/status/tsdb` + метрики `vm_indexdb_*` (`vm_indexdb_cache_*`), `vm_data_size_bytes` (см. [http_api_reference.md](./http_api_reference.md)).

## Запуск, WAL replay и снапшоты

### Поведение при старте

1. **Блокировка (`flock`)** — процесс захватывает lock-файл в `-storageDataPath`; второй экземпляр на том же пути не стартует.
2. **Загрузка кэшей** — persistent кеши (`cache/metricID_tsid`, `cache/metricID_metricName`) считываются с диска; in-memory кеши (`indexdb/indexBlocks`, `indexdb/dataBlocks`, `indexdb/tagFilters`) реконструируются из indexdb.
3. **WAL replay** — если shutdown был аварийным, из `wal/` восстанавливаются сэмплы, не успевшие попасть в parts. Это может занимать минуты на больших объёмах. Чистый `systemctl stop` сбрасывает in-memory буферы на диск — replay минимален.
4. **Инициализация indexdb** — для текущего и предыдущего часа создаются in-memory hash-слои (`currHourMetricIDs`, `prevHourMetricIDs`); индекс ротируется каждые 10 минут (`nextHourMetricIDs` → `currHourMetricIDs` → `prevHourMetricIDs`). Флаг `-storage.idbPrefillStart` (по умолчанию `1h`) задаёт, за сколько времени до полуночного роутит pre-fill для следующего дня, чтобы избежать CPU-с spikes в 00:00 UTC (см. issue #430).

### Снапшоты для бэкапа

Снапшот — застывшая копия данных в `{storageDataPath}/snapshots/`. Именно по снапшоту работает [vmbackup/vmrestore](./vmbackup_restore.md).

```bash
# Создать снапшот
curl -s -X POST 'http://localhost:8428/snapshot/create'
# → {"status":"ok","snapshot":"20260120T120000.123"}

# Список
curl -s 'http://localhost:8428/snapshot/list'

# Удалить (не забудьте — снапшоты занимают диск!)
curl -s -X DELETE 'http://localhost:8428/snapshot/20260120T120000.123'
```

```bash
# Резервная копия через rsync (без остановки)
SNAP=$(curl -s 'http://localhost:8428/snapshot/list' | jq -r '.snapshots[-1]')
rsync -a --delete "/var/lib/victoria-metrics/snapshots/${SNAP}/" backup-host:/backup/vm/
curl -X DELETE "http://localhost:8428/snapshot/${SNAP}"
```

## Поиск и устранение неисправностей

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| Много small parts, медленные запросы | Merge не успевает (недостаточно IOPS/CPU) | Мониторить `vm_merges_total` и `vm_pending_merges`; повысить IOPS; верхние параметры `-storage*` |
| Диск переполняется, данные не почищаются | Retention партиций ещё не сработал, либо данные в WAL | Проверить `-retentionPeriod`; размер `wal/`; при необходимости удалить партицию вручную при остановленном сервисе |
| Медленные старты | Большой WAL (WAL replay) | Считается нормальным; уменьшить `-inmemoryDataFlushInterval` при часто падающих инстансах |
| Крашаются merge | Недостаточно памяти | `-memory.allowedPercent`; уменьшить параллелизм merge через `-maxConcurrentInserts`/планировщик |
| Разрастается indexdb и RAM на метаданные | Много уникальных рядов (кардинальность) | Найти высококардинальные лейблы через `/api/v1/status/tsdb` или [vmestimator](./vmestimator.md); вычищать `relabel_configs` |
| High cache miss | Мало RAM на кеши, cache miss'и растут | Проверить `vm_cache_misses_total{type="indexdb/dataBlocks"}` и `vm_cache_hits_total`; увеличить `-storage.cacheSize*` или RAM; при необходимости удалить кеш через `reset_cache_on_startup` |

## Рекомендации по эксплуатции

- Регулярно смотрите `vm_parts` на стороне хранилища — это индикатор здоровья merge.
- Не размещайте `-storageDataPath` на NFS/CIFS — только локальный диск/RAID; в cluster каждый vmstorage — своя ФС.
- Не удаляйте `wal/` вручную при работающем или остановленном аварийно сервисе — потеряете данные.
- Для дедупликации включайте `-dedup.minScrapeInterval` (иначе одинаковые серии из HA-пар пишутся дважды и merge становится избыточным).
- Планируйте capacity через [формулы из overview](./overview.md) и `vmestimator` для кардинальности.
- **Force merge** (`POST /internal/force_merge?partition_prefix=YYYYMMDD`) полезен для освобождения диска после массового `delete_series` — удалённые серии удаляются из indexdb и чистятся при слиянии. Делайте в окно низкой нагрузки, используя `-forceMergeAuthKey`.
- **Force flush** (`POST /internal/force_flush`) сбрасывает in-memory parts на диск — используйте перед плановой остановкой или shutdown, чтобы минимизировать WAL replay.
- **Сброс кэша** через `reset_cache_on_startup` помогает при подозрении на corrupted cache или для forced cache rebuild после изменения `-storage.cacheSize*`;

## Ограничения и особые случаи

- In-memory parts не гарантируют durability до flush: при `kill -9` теряется «окно» до `-inmemoryDataFlushInterval`, остальное покрывает WAL.
- Индекс ротируется каждые 10 минут; долгий аптайм с большим churn («взрыв кардинальности» и исчезновение) раздувает indexdb — следите за `vm_indexdb_*`.
- Cluster: `vmstorage` → `vmselect` — внимание к `-search.maxQueryDuration` и `dedup` на чтении.
- **Read-only mode** активируется автоматически при свободном месте `< -storage.minFreeDiskSpaceBytes`: хранилище перестаёт принимать новые данные, но продолжает обслуживать запросы на чтение. Снимается при освобождении диска.
- **Big parts** (>4 GiB) при чтении обходят page cache ОС, чтобы не вытеснять «горячее» содержимое; это снижает cache hit ratio для больших исторических запросов, но повышает общую производительность.
- **WAL на маленькой скорости записи** — при низкой ingestion rate WAL растёт медленно, но может держать данные дольше, чем `-inmemoryDataFlushInterval`; при длительном простое WAL replay увеличивается.

## Дополнительная информация

### См. также

- [VictoriaMetrics: обзор](./overview.md) — capacity-планирование и ограничения;
- [Отчёт о кардинальности (vmestimator)](./vmestimator.md);
- [VictoriaLogs: внутреннее устройство](./victorialogs_internals.md) — аналогичный движок для логов;
- [HTTP API: диагностика RAM/кардинальности](./http_api_reference.md) — `/api/v1/status/tsdb`, `active_queries`;
- [vmbackup / vmrestore](./vmbackup_restore.md) — инкрементальный бэкап через снапшоты.
