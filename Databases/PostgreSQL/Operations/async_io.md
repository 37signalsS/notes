# Асинхронный ввод-вывод в PostgreSQL (AIO)

**Актуально для:** PostgreSQL 18 / 17 (readstream); раздел «PG 19» — preview ветки 19 (Beta 4, 2026-09)

Подсистема асинхронного ввода-вывода: зачем backend'ам перестать ждать каждую страницу, какие режимы и параметры настраивать, как включить io_uring в контейнере и как измерить эффект. Основной файл по теме; смежные аспекты — [io_uring на уровне ядра](../../../Linux/Core/kernel/io_uring.md), [Внутреннее устройство VACUUM](../Concepts/vacuum_internals.md), [Наблюдаемость](./observability.md), [Оптимизация производительности](./performance_tuning.md).

## Определения

- **AIO (Asynchronous I/O)** — подсистема асинхронного ввода-вывода (PG 18): backend ставит запросы на чтение в очередь и продолжает обработку запроса, вместо того чтобы замирать в ожидании каждой страницы.
- **Backend** — серверный процесс, обрабатывающий клиентское соединение. В этой заметке «backend» — процесс СУБД, а не код приложения.
- **Страница (page)** — единица хранения PostgreSQL, по умолчанию 8 КБ (`BLCKSZ`).
- **shared_buffers** — общий кэш страниц, разделяемый между всеми backend'ами.
- **Page cache** — кэш ядра. Чтение, не попавшее в shared_buffers (`shared read`), обслуживается из page cache или с диска.
- **Syscall** — вызов функции ядра (чтение файла, выделение памяти) с переключением контекста user→kernel; дорогая операция, которую AIO минимизирует.
- **Readstream** — API потокового чтения (PG 17): страницы читаются через `preadv` с хинтами для ядра и объединением смежных чтений.
- **Combining (батчинг)** — объединение нескольких запросов на чтение в одну операцию большего размера.
- **io_uring** — асинхронный интерфейс ядра Linux через разделяемые кольца submission/completion.
- **I/O-handle** — внутренний дескриптор асинхронной операции в подсистеме AIO; каждому занятому handle'у соответствует строка в представлении `pg_aios`.
- **Wait event** — событие ожидания серверного процесса (`wait_event_type`/`wait_event` в `pg_stat_activity`); для AIO это `AioIoCompletion`, `AioIoUringExecution`, `AioIoUringSubmit` и `IoWorkerMain`.

## Базовые концепции

### Стек чтения страницы

Запрос на страницу проходит цепочку: backend → shared_buffers (попадание — `shared hit`, отдача сразу) → page cache ядра → диск. Следствие: асинхронность имеет смысл только там, где реально идёт обращение к диску; если данные в shared_buffers, тюнинг I/O ничего не даст.

Особенность реализации: при seq scan читаемые страницы не попадают в shared_buffers — они читаются в отдельный кольцевой буфер (32 слота × 8 КБ = 256 КБ), чтобы не вытеснять полезные страницы. В shared_buffers попадают только страницы, признанные часто используемыми (алгоритм Clock Sweep).

### Почему синхронное чтение — узкое место

До PG 17 чтение было синхронным: backend запрашивал у ядра одну страницу и замирал в состоянии D (ожидание диска), не обрабатывая ранее полученные данные. Проблема не в скорости диска, а в глубине очереди, равной 1: современные NVMe-контроллеры параллельно обслуживают десятки запросов и имеют собственные конвейеры, но PostgreSQL использовал лишь малую долю их пропускной способности. Масштаб: `SELECT *` по таблице 500 ГБ — это ~61 млн страниц (500 ГБ / 8 КБ), десятки минут чистого ожидания даже на быстром диске.

Метафора: синхронное чтение — официант, который стоит на кухне и ждёт заказ; асинхронное — официант, который несёт заказ следующему клиенту и возвращается, когда заказ готов. Чинить надо официантов (backend), а не кухню (диск): более быстрый диск при глубине очереди 1 почти ничего не даёт.

### Характер чтения определяет выигрыш

| Тип сканирования | Характер чтения | Выигрыш от AIO |
| :--- | :--- | :--- |
| Sequential Scan | последовательное, страница за страницей | высокий: чтение известно заранее, batching эффективен |
| Bitmap Heap Scan | точечное, но список страниц известен заранее | высокий: весь список можно сразу поставить в очередь |
| Index Scan | случайное, следующая страница неизвестна до чтения текущей | низкий: предсказать и предзагрузить нечего |

Index scan — самый частый случай, где асинхронное чтение не помогает: адрес следующей страницы становится известен только после чтения текущей (связный список страниц в индексе), поэтому ни prefetch ядра, ни batching не работают.

### Эволюция: PG 17 → 18

- **PG 17 (readstream)**: чтение через `preadv` с хинтами (`posix_fadvise`) для ядра и combining смежных чтений (`io_combine_limit`, default 128 КБ). Частичное решение: данные сначала попадают в page cache ядра, а оттуда их нужно ещё тащить в userspace — лишний syscall и копирование; на сетевых дисках prefetch ядра малоэффективен, а при случайном чтении (bitmap heap scan) хинты бесполезны.
- **PG 18 (AIO, релиз 2025-09-25)**: полноценная подсистема (Andres Freund, Thomas Munro, Nazir Bilal Yavuz, Melanie Plageman). Backend не блокируется на чтении; появились `io_method`, `io_workers`, `io_max_concurrency`, представление `pg_aios`; дефолты `effective_io_concurrency` и `maintenance_io_concurrency` повышены с 1/10 до 16 («более точно отражает современное железо»). Бонус: значения `effective_io_concurrency`/`maintenance_io_concurrency` больше нуля теперь работают и на системах без `fadvise()`.

## Конфигурация

### Предварительные требования

- PostgreSQL 18+ для полноценной подсистемы AIO (PG 17 — только readstream/batching).
- Для `io_method = io_uring`: ядро Linux 5.6+, сборка с liburing, разрешённые вызовы `io_uring_*` в seccomp-профиле (в контейнере).
- Права на мониторинг: `pg_aios` и `pg_stat_io` читаются суперпользователем или ролями с `pg_read_all_stats`.
- Для замеров времени I/O: `track_io_timing = on` (менять через `SET` может только суперпользователь).

### Режимы io_method

| Режим | Как работает | Плюсы | Минусы |
| :--- | :--- | :--- | :--- |
| `sync` | асинхронно-допустимое I/O выполняется синхронно (поведение PG ≤17) | максимальная совместимость | нет выигрыша от AIO |
| `worker` (default) | пул I/O-воркеров забирает запросы из очереди и читает блоками (pread/preadv — механизм PG 17) | работает везде (Linux, Windows, macOS), не требует особого ядра | оверхед на межпроцессное взаимодействие и переключение контекста |
| `io_uring` | backend записывает запросы в submission ring (обычная запись в память, без syscall), ядро выполняет и кладёт результаты в completion ring | нет посредника-процесса, глубокая очередь, максимальная производительность при большом числе мелких I/O | только Linux; нужна сборка с `--with-liburing`; ядро 5.6+; блокируется seccomp в контейнерах |

Кольца io_uring создаются под каждый процесс — общей очереди нет, данные между процессами не передаются. `io_method` — параметр уровня postmaster: задаётся только в `postgresql.conf`/командной строке и требует перезапуска сервера.

В PG 18 асинхронны только чтения: запись (WAL, чекпоинты) остаётся синхронной — осознанный выбор ради гарантий сохранности и консистентности (запись должна попасть на диск до подтверждения транзакции).

### Параметры

| Параметр | Default | Контекст | Назначение |
| :--- | :--- | :--- | :--- |
| `io_method` | `worker` | postmaster (restart) | режим AIO: `sync` / `worker` / `io_uring` |
| `io_workers` | 3 | sighup (reload) | число I/O-воркеров (только для `io_method=worker`); диапазон 1–32; в ветке 19 заменён парой `io_min_workers`/`io_max_workers` |
| `io_combine_limit` | 128kB (16 блоков) | user (сессия) | максимальный размер объединённого I/O; диапазон 8 КБ–256 КБ |
| `io_max_combine_limit` | 128kB | postmaster (restart) | верхняя граница для `io_combine_limit`; типичный максимум на Unix — 1 МБ (на Windows — 128 КБ). Если `io_combine_limit` задан выше — значение молча обрезается до лимита, ошибки не будет: поднимать нужно оба параметра |
| `io_max_concurrency` | -1 | postmaster (restart) | макс. число одновременных I/O-операций на процесс; -1 = авто (на основе `shared_buffers` и максимального числа процессов — `max_connections`, `autovacuum_worker_slots`, `max_worker_processes`, `max_wal_senders` — не более 64); диапазон -1–1024 |
| `effective_io_concurrency` | 16 (PG 18) / 1 (PG ≤17) | user (сессия) | число одновременных I/O, которые сессия инициирует параллельно (SELECT, bitmap heap scan); диапазон 1–1000, 0 отключает выдачу асинхронных запросов; на системах с поддержкой fadvise также задаёт дистанцию prefetch; переопределяется на уровне tablespace |
| `maintenance_io_concurrency` | 16 (PG 18) / 10 (PG ≤17) | user (сессия) | то же для обслуживающих операций (VACUUM, ANALYZE и т.п.); переопределяется на уровне tablespace |

`io_max_concurrency` и `effective_io_concurrency` — разные параметры: первый ограничивает общее число операций in flight на процесс (действует и на SELECT, и на VACUUM), второй задаёт, сколько операций сессия инициирует параллельно. Менять нужно оба, иначе выигрыш будет наполовину.

Смысл `io_workers`: если воркеров 3 и три чтения уже в состоянии D, четвёртое чтение встанет в очередь — увеличение числа воркеров повышает параллелизм чтения. Рекомендация с лекции (со слов контрибьютора Tomas Vondra): порядок 1/4 от числа ядер, иногда больше, но не меньше.

**Переопределение на уровне tablespace:** `effective_io_concurrency` и `maintenance_io_concurrency` можно задать для конкретного tablespace — полезно, когда «горячие» данные лежат на быстром NVMe, а архив — на медленном хранилище:

```sql
ALTER TABLESPACE fast_ssd SET (effective_io_concurrency = 200, maintenance_io_concurrency = 200);
```

### Сборка, ядро, контейнеры

- **Сборка**: `io_uring` доступен только при сборке с `--with-liburing` (PostgreSQL находит liburing через pkg-config; для сборки через Meson — опция `-Dliburing`). Проверка: `pg_config --configure` должен содержать `--with-liburing`; попытка `io_method = io_uring` без поддержки завершается ошибкой `invalid value for parameter "io_method": "io_uring". Available values: sync, worker`.
- **Ядро**: формально io_uring появился в Linux 5.1, но опкоды `IORING_OP_READ`/`IORING_OP_WRITE` (и их vectored-варианты `IORING_OP_READV`/`IORING_OP_WRITEV`), которые использует PostgreSQL, доступны только с 5.6. На ядрах 5.1–5.5 сервер стартует, но подключения падают с `EINVAL` (BUG #19369 — упущение в документации, признанное мейнтейнерами; в обсуждении предложен патч с явной FATAL-диагностикой при старте). Требуйте ядро 5.6+.
- **Docker**: стандартный seccomp-профиль Docker блокирует системные вызовы `io_uring_setup`, `io_uring_enter`, `io_uring_register` — в контейнере io_uring не заработает из коробки (сервер стартует, но режим недоступен; пользовательский отчёт — docker-library/postgres#1365). Решение — кастомный seccomp-профиль: дефолтный профиль Docker плюс три вызова в allow-лист. Не используйте `seccomp=unconfined` — снимает всю защиту. Полезно также поднять лимит открытых файлов (`ulimit -n`).
- **Alpine**: образы `postgres:18-alpine` на момент релиза 18.0 (2025-09-25) собирались без liburing; поддержка добавлена через неделю, 2025-09-30 (docker-library/postgres#1366, «Add liburing support to 18+»). Актуальные официальные образы (debian и alpine) собраны с `liburing-dev` — проверяйте при использовании старых или сторонних образов.

Пример кастомного seccomp-профиля (иллюстративный — на практике профиль строят от дефолтного Docker-профиля, добавляя три вызова к его allow-листу):

```json
{
  "defaultAction": "SCMP_ACT_ERRNO",
  "syscalls": [
    {
      "names": ["io_uring_setup", "io_uring_enter", "io_uring_register"],
      "action": "SCMP_ACT_ALLOW"
    }
  ]
}
```

## Мониторинг и валидация

```sql
-- Текущий режим и параметры (значения после старта/reload)
SHOW io_method;
SELECT name, setting, context FROM pg_settings
WHERE name IN ('io_method','io_workers','io_combine_limit',
               'io_max_combine_limit','io_max_concurrency',
               'effective_io_concurrency','maintenance_io_concurrency');

-- In-use I/O-handle'ы: что прямо сейчас in flight (PG 18+)
SELECT pid, state, operation, off, length, result FROM pg_aios;

-- Накопленная I/O-статистика по backend_type/context/объекту (PG 17+)
SELECT * FROM pg_stat_io ORDER BY read_bytes DESC;

-- События ожидания I/O прямо сейчас: кто и на чём стоит
SELECT wait_event_type, wait_event, count(*) AS n
FROM pg_stat_activity
WHERE wait_event_type = 'IO'
GROUP BY 1, 2 ORDER BY n DESC;

-- I/O-статистика конкретного backend'а по pid (PG 18+; <pid> — pid из pg_stat_activity)
SELECT * FROM pg_stat_get_backend_io(<pid>);
```

- **`pg_aios` (PG 18+)** — по одной строке на каждый занятый I/O-handle. Столбцы: `pid`, `io_id` (идентификатор handle'а; переиспользуется после завершения, при этом инкрементируется `io_generation`), `state`, `operation` (`invalid` / `readv` / `writev`), `off`, `length`, `target` (`smgr` — I/O по relations), `handle_data_len` (для I/O в shared_buffers/temp_buffers — число буферов), `raw_result` (низкоуровневый результат, NULL до завершения), `result`, `target_desc`, флаги `f_sync`, `f_localmem`, `f_buffered`. Состояния (`state`): `HANDED_OUT` (дескриптор занят, но не используется), `DEFINED` (известны параметры операции), `STAGED` (готова к выполнению), `SUBMITTED` (отправлена воркеру или в ядро), `COMPLETED_IO` (завершена, результат не обработан), `COMPLETED_SHARED` (завершена общая обработка — например, проверена контрольная сумма страницы), `COMPLETED_LOCAL` (завершена backend-локальная обработка). Значения `result`: `UNKNOWN`, `OK`, `PARTIAL` (завершена без ошибки, но не все данные — остаток обычно добирается отдельной операцией), `WARNING` (например, повреждённый буфер при `zero_damaged_pages`), `ERROR`. Чтение доступно суперпользователю и ролям с `pg_read_all_stats`. Если представление всегда пусто — асинхронность не работает (режим `sync` или глубина очереди 1).
- **`pg_stat_io` (PG 17+)** — накопленная статистика: по одной строке на комбинацию `backend_type` × `object` (`relation`, `temp relation`, `wal`) × `context` (`normal`, `init`, `vacuum`, `bulkread`, `bulkwrite`). Столбцы: `reads`/`read_bytes`/`read_time`, `writes`/`write_bytes`/`write_time`, `writebacks`/`writeback_time`, `extends`/`extend_bytes`/`extend_time`, `hits`, `evictions`, `reuses`, `fsyncs`/`fsync_time`, `stats_reset`. Столбцы `*_time` заполняются только при `track_io_timing = on` (для WAL — `track_wal_io_timing`), иначе 0. Полезный запрос — средний размер чтения:

```sql
SELECT backend_type, context, object, reads, read_bytes, read_time,
       read_bytes::numeric / NULLIF(reads, 0) AS avg_read_bytes
FROM pg_stat_io WHERE reads > 0;
-- → avg_read_bytes ≈ 8192: батчинг не работает
-- → avg_read_bytes ≈ 131072 (io_combine_limit): батчинг работает
```

  Особенности интерпретации (из документации): статистика не различает чтение с диска и попадание в page cache ядра — используйте её вместе с `iostat`; I/O при перемещении таблицы между tablespace (вне shared_buffers) не отслеживается; высокий `evictions` может указывать на малый `shared_buffers`, а массовые `fsyncs` клиентских backend'ов — на ошибку конфигурации shared_buffers/checkpointer. Счётчики сбрасываются `SELECT pg_stat_reset('io');`, per-backend — `pg_stat_reset_backend_stats()`. Внутри одной транзакции значения кэшируются и не меняются — для интерактивного анализа вызовите `pg_stat_clear_snapshot()` или завершите транзакцию.
- **`pg_stat_activity`** — запросы in flight; в режиме `worker` события ожидания I/O переносятся на I/O-воркеры, а не на backend. Wait events, специфичные для AIO (PG 18): `AioIoCompletion` (ожидание завершения I/O другим процессом), `AioIoUringExecution` (ожидание выполнения I/O через io_uring), `AioIoUringSubmit` (ожидание отправки I/O в io_uring), `IoWorkerMain` (простой I/O-воркера в основном цикле); плюс `DataFilePrefetch` (асинхронный prefetch, PG 17+) и `BufferIo` (буферный I/O). Массовые `AioIoUringSubmit`/`AioIoUringExecution` — признак перегрузки io_uring или отстающего хранилища.
- **EXPLAIN ANALYZE** с `track_io_timing = on` — в выводе узлов появляется строка `I/O Timings` (например, `I/O Timings: read=...`): сколько реально времени ушло на ожидание I/O, отдельно от времени обработки. Сравнивайте именно I/O Timings, а не общее время узла. В PG 19 (preview) добавлена явная опция `EXPLAIN (ANALYZE, IO)` для отчёта об асинхронном I/O и серверная переменная `auto_explain.log_io`.
- **`iostat -x`** — утилизация диска vs время запроса: если запрос идёт долго, а утилизация низкая (например, 4%) — проблема не в диске, а в глубине очереди чтения.
- **fio** — проверка хранилища независимо от PostgreSQL: размер блока (8 КБ vs 128 КБ), глубина очереди (`iodepth`), случайное vs последовательное чтение.
- **dm-delay** — device-mapper target для эмуляции медленного диска (например, +500 мс) — позволяет посмотреть поведение на диске с высокой задержкой (сетевое хранилище, SAN).
- **Проверка io_uring на уровне ОС** — дескрипторы io_uring видны в `/proc/<PID>/fd/` как `anon_inode:io_uring`; трассировка отправки запросов — `bpftrace -e 'tracepoint:io_uring:io_uring_submit_sqe { @[comm] = count(); }'` (подробнее — в [диагностике дискового I/O в Linux](../../../Linux/Diagnostics/Performance/DiskIO/diagnostic_tools_comparison.md)).

**Методика замера эффекта:**

1. Перезапустить PostgreSQL (для `io_method`), сбросить кэши: `echo 3 > /proc/sys/vm/drop_caches` (и кэш ФС, чтобы не было влияния ранее прочитанных файлов).
2. Сбросить статистику: `SELECT pg_stat_reset('io');` — иначе в замер попадёт накопленное ранее.
3. Включить `track_io_timing`, выполнить запрос, зафиксировать I/O Timings и `pg_stat_io`.
4. Переключить режим/параметр, повторить. Менять только одно значение за раз.
5. Если в EXPLAIN везде `shared hit` — кэши не были сброшены, замер бессмысленен.

## Troubleshooting

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `invalid value for parameter "io_method": "io_uring". Available values: sync, worker` | сборка без `--with-liburing` | пересобрать с `--with-liburing` (или `-Dliburing`) или использовать другой образ |
| Сервер стартует с `io_method=io_uring`, но подключения падают с `EINVAL` | ядро 5.1–5.5 (опкоды READ/WRITE/READV/WRITEV появились в 5.6) | ядро 5.6+ |
| io_uring не работает в Docker | seccomp-профиль блокирует вызовы `io_uring_*` | кастомный seccomp-профиль с тремя вызовами |
| `io_combine_limit` не применяется | значение выше `io_max_combine_limit`, молча обрезается | поднять оба параметра |
| Асинхронности «нет» после апгрейда на 18 | старый конфиг: `effective_io_concurrency = 1` (дефолт ≤17) убивает параллельные выдачи | проверить все concurrency-параметры; дефолт PG 18 — 16 |
| `pg_aios` всегда пуст при активном чтении | режим `sync` или concurrency-параметры = 1 | переключить `io_method`, поднять concurrency |
| `avg_read_bytes` ≈ 8 КБ при больших чтениях | батчинг не работает (режим sync или лимиты) | проверить `io_method`, `io_combine_limit` |
| `read_time`/`write_time` в `pg_stat_io` = 0 при активном чтении | выключен `track_io_timing` | `SET track_io_timing = on` (или в postgresql.conf) |
| `pg_stat_io` не меняется между замерами в одной сессии | статистика кэшируется на время транзакции | `SELECT pg_stat_clear_snapshot();` или COMMIT между замерами |
| Массовые `AioIoUringSubmit`/`AioIoUringExecution` в `pg_stat_activity` | io_uring перегружен или хранилище не успевает | проверить `io_max_concurrency`, глубину очереди и нагрузку на хранилище (`iostat -x`) |
| Аномалии после включения AIO | нестабильное хранилище/конфигурация | вернуть `io_method = sync` и проверить базовое поведение |

## Best Practices

**Когда асинхронное чтение помогает:** аналитические нагрузки с seq scan и bitmap heap scan, VACUUM/ANALYZE (охватывают всю таблицу), прогрев кэша (`pg_prewarm`), bulk-чтение. Особенно заметно на медленных и сетевых дисках с высокой задержкой.

**Когда бесполезно или вредит:** данные уже в shared_buffers (нет обращения к диску); write-heavy OLTP (мало чтения); CPU-bound нагрузка (нет ожидания диска); плохой план запроса (вложенные подзапросы, хаотичное чтение); проблемы с записью (WAL не успевает, чекпоинты). Index scan почти не ускоряется — следующая страница непредсказуема.

**Порядок тюнинга:**

1. Проверить сборку (`pg_config --configure`), версию ядра (5.6+), активный `io_method`.
2. Начать с `worker` (работает везде) — уже даёт batching из PG 17.
3. Проверить, что `io_max_concurrency` не 1 и `effective_io_concurrency`/`maintenance_io_concurrency` разумны (в PG 18 дефолт 16).
4. Только после этого крутить `io_combine_limit` (и `io_max_combine_limit` вместе с ним) — перебор может навредить.
5. Попробовать `io_uring` при глубокой очереди и Linux-сборке с liburing.

**Откат (cleanup):** вернуть `io_method = sync` (или `worker`) в `postgresql.conf` и перезапустить сервер; concurrency-параметры вернуть к дефолтам через `ALTER SYSTEM`/`postgresql.conf` + reload; в контейнере — вернуть стандартный seccomp-профиль. После отката проверить `pg_aios` (должно быть пусто при отсутствии чтения) и отсутствие аномалий в `pg_stat_io`.

**Замеры с лекции** (сетевой диск с высокой задержкой, таблица 300 ГБ, холодный кэш): PG 17 с batching ≈ 16 с; PG 18 `sync` ≈ 15 с; `worker` ≈ 10 с; `io_uring` ≈ 5,7 с — примерно 3× к обычному чтению. Наблюдения лектора: при эффективной глубине очереди ~32 режимы примерно равны; при 64 `io_uring` заметно быстрее (~2×); `io_uring` продолжает ускоряться до ~1024 одновременных запросов, тогда как `worker` выходит на плато. VACUUM при распараллеливании ускоряется до десятков раз (замеры лектора). Caveat: в режиме `io_uring` финальная обработка (включая проверку контрольной суммы страницы, состояние `COMPLETED_SHARED`) выполняется самим backend, а не отдельным процессом — при малой глубине очереди подсчёт контрольных сумм не распараллеливается, и `worker` может оказаться быстрее.

**PG 19 (preview, Beta 4 от 2026-09-24):** автоматическая регулировка пула I/O-воркеров (Thomas Munro) — новые параметры `io_min_workers` (default 2), `io_max_workers` (default 8), `io_worker_launch_interval` (default 100 мс — минимальный интервал между запусками воркеров, защита от всплесков) и `io_worker_idle_timeout` (default 1 мин — через сколько простоя лишний воркер завершается): задаётся диапазон, а число воркеров меняется под характер нагрузки. Параметр `io_workers` в ветке 19 отсутствует — его роль берёт на себя автоматическая регулировка между `io_min_workers` и `io_max_workers`. Дефолт `io_method` остаётся `worker`, запись по-прежнему не асинхронна. Другие изменения AIO в 19: улучшено планирование read-ahead для больших запросов (Andres Freund), добавлены `EXPLAIN (ANALYZE, IO)` и `auto_explain.log_io` (Tomas Vondra), wait events для COPY FROM/TO на pipe/file/program.

## Дополнительная информация

- [Resource Consumption (io_method, io_workers, io_combine_limit, io_max_concurrency)](https://www.postgresql.org/docs/current/runtime-config-resource.html) — официальная документация по параметрам
- [pg_aios](https://www.postgresql.org/docs/current/view-pg-aios.html) — системное представление in-use I/O-handle'ов
- [pg_stat_io](https://www.postgresql.org/docs/current/monitoring-stats.html#MONITORING-PG-STAT-IO-VIEW) и [wait events](https://www.postgresql.org/docs/current/monitoring-stats.html#MONITORING-PG-STAT-ACTIVITY-VIEW) — накопленная I/O-статистика и события ожидания
- [Release 18](https://www.postgresql.org/docs/current/release-18.html) — описание AIO-подсистемы (релиз 2025-09-25)
- [Release 19 (devel)](https://www.postgresql.org/docs/devel/release-19.html) — автоматическая регулировка пула I/O-воркеров
- [--with-liburing](https://www.postgresql.org/docs/current/install-make.html#CONFIGURE-OPTION-WITH-LIBURING) — опция сборки
- [io_uring на уровне ядра](../../../Linux/Core/kernel/io_uring.md) — устройство интерфейса, seccomp, отключение через `io_uring.disabled`
- [Диагностика дискового I/O в Linux](../../../Linux/Diagnostics/Performance/DiskIO/diagnostic_tools_comparison.md) — обнаружение io_uring-нагрузки, невидимой для iotop/pidstat
- [Внутреннее устройство VACUUM](../Concepts/vacuum_internals.md) — влияние AIO на VACUUM
- [Наблюдаемость](./observability.md) — pg_stat_io и смежные представления
- [Оптимизация производительности](./performance_tuning.md) — параметры памяти и I/O
