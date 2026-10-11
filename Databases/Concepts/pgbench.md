# pgbench

**Актуально для:** PostgreSQL 10+ (основной синтаксис); отдельные параметры требуют 13+

## Определения

**pgbench** — встроенный инструмент PostgreSQL для бенчмаркинга и нагрузочного тестирования. Изначально имитирует TPC-B нагрузку (высокая интенсивность обновлений) с 4 таблицами: `pgbench_accounts`, `pgbench_branches`, `pgbench_history`, `pgbench_tellers`. В PostgreSQL 10+ доступны расширенные профили и поддержка кастомных SQL-скриптов. Использует Closed Loop модель.

**TPC-B (в контексте pgbench)** — упрощенный профиль нагрузки, не являющийся полноценным TPC-C. Включает SELECT, UPDATE и INSERT в фиксированных пропорциях. Для полноценного TPC-C используйте [HammerDB](./hammerdb.md).

---

## Установка

pgbench входит в дистрибутив PostgreSQL и не требует отдельной установки:

```bash
# Ubuntu / Debian
sudo apt install -y postgresql-client

# RHEL / CentOS / Rocky Linux
sudo dnf install -y postgresql
```

### Проверка версии

```bash
pgbench --version  # → pgbench (PostgreSQL) 16.x
```

---

## Подготовка данных

### Стандартная инициализация (TPC-B)

```bash
# Scale factor 100 = 10 млн строк (100 * 100,000 accounts)
pgbench -i -s 100 mydatabase
# → Создает 4 таблицы:
#   pgbench_accounts (10,000,000 строк)
#   pgbench_branches (100,000 строк)
#   pgbench_tellers  (1,000,000 строк)
#   pgbench_history  (не заполняется при инициализации)

# Проверка данных:
psql -d mydatabase -c "SELECT COUNT(*) FROM pgbench_accounts;"
# → 10000000
```

### Параметры инициализации

| Параметр | Описание | Рекомендация |
| :--- | :--- | :--- |
| `-i` | Режим инициализации (initialize) | Обязательный для первого запуска |
| `-s` | Scale factor (множитель размера) | SF=100 для 10 млн строк |
| `-j` | Параллелизм инициализации (threads) | Ускоряет создание больших таблиц |
| `--fillfactor` | Процент заполнения страниц | 80–90 для write-heavy workloads; по умолчанию 100 |
| `-n` / `--no-vacuum` | Пропустить VACUUM после инициализации | Ускоряет инициализацию для больших SF; запустите `ANALYZE` вручную перед тестом |

---

## Подготовка окружения и изоляция

pgbench генерирует нагрузку от имени операционной системы. Если клиент и сервер PostgreSQL находятся на одном хосте, они конкурируют за CPU, RAM и I/O, что искажает результаты.

### 1. Отдельный хост для нагрузчика

Выделите отдельный сервер или ВМ для запуска pgbench. Минимальное расстояние — отдельный физический хост. Если это невозможно, используйте отдельную ВМ на том же хосте с жестким лимитом CPU (`cgroups` / `taskset`).

### 2. Ограничение ресурсов клиента

Чтобы pgbench сам не стал узким местом:

```bash
# Ограничение числа открытых файлов
ulimit -n 65536

# Привязка pgbench к конкретным ядрам (пример: ядра 0-7)
taskset -c 0-7 pgbench -c 50 -j 8 -T 600 mydatabase

# Снижение приоритета процесса
nice -n 10 pgbench -c 50 -j 8 -T 600 mydatabase
```

### 3. Сеть и подключения

- При тестировании через сеть используйте `-h` с IP сервера, а не `localhost`, чтобы учесть задержку сети.
- Для тестирования через PgBouncer указывайте порт PgBouncer (`-p 6432`).
- Избегайте тестирования через SSL на локальном хосте — это добавляет overhead CPU.

### 4. Файловая система для логов

При использовании `--log` создается множество файлов `pgbench_log_*.log`. Размещайте их на отдельном диске от данных PostgreSQL, чтобы логи не конкурировали за I/O с WAL и data pages.

---

## Запуск теста

### Стандартный режим (TPC-B)

```bash
# Запуск теста:
# -c: клиенты (параллельные соединения)
# -j: потоки (внутренняя параллелизация pgbench)
# -T: время в секундах
# -S: только чтение (select-only)
# -M: protocol (extended, simple, prepared)
pgbench -c 50 -j 8 -T 600 -S mydatabase
# → Тест "только чтение" с 50 клиентами в течение 10 минут

# Запуск смешанной нагрузки (чтение + запись, по умолчанию):
pgbench -c 50 -j 8 -T 600 mydatabase
# → По умолчанию: SELECT (70%), UPDATE (14%), INSERT (14%), DELETE (2%)
```

### Ключевые параметры

| Параметр | Описание | Рекомендация |
| :--- | :--- | :--- |
| `-c` | Количество параллельных клиентов | Начинайте с 1, увеличивайте до Saturation Point |
| `-j` | Количество потоков pgbench | Равно количеству ядер CPU клиента |
| `-T` | Время теста в секундах | Минимум 300, для Steady State — 1800 |
| `-S` | Только чтение (select-only) | Для тестирования реплик |
| `-M` | Протокол (extended/simple/prepared) | `prepared` снижает overhead парсинга |
| `--log` | Логирование каждой транзакции | Для детального анализа |
| `-P` | Интервал вывода прогресса в секундах | `1` или `5` для длительных тестов |
| `--latency-limit` | Максимальная задержка транзакции в мс (PostgreSQL 13+) | Прерывает транзакцию при превышении; помогает выявить tail latency |
| `--report-per-command` | Статистика по каждому типу запроса | В совокупности с `--log` |

### Расширенные профили (PostgreSQL 10+)

```bash
# Протокол prepared (снижает overhead парсинга):
pgbench -c 50 -j 8 -T 600 -M prepared mydatabase

# Протокол extended (по умолчанию, самый безопасный):
pgbench -c 50 -j 8 -T 600 -M extended mydatabase

# Логирование каждой транзакции для анализа:
pgbench -c 32 -j 8 -T 300 --log --log-prefix=pgbench_log mydatabase
# → Создает файлы pgbench_log_*.log с деталями каждой транзакции
```

---

## Настройка PostgreSQL для бенчмаркинга

Дефолтная конфигурация PostgreSQL оптимизирована для безопасности и совместимости, а не для максимальной производительности. Перед бенчмаркингом настройте ключевые параметры.

### Критические параметры

| Параметр | Рекомендация для бенчмаркинга | Почему |
| :--- | :--- | :--- |
| `shared_buffers` | 25–40% от RAM | Оптимальный размер Buffer Pool. Оставьте место под кэш ОС. |
| `work_mem` | 4–64 МБ | Слишком мало — временные файлы на диск; слишком много — утечка памяти при параллелизме. |
| `maintenance_work_mem` | 1–2 ГБ | Ускоряет `CREATE INDEX` и `VACUUM` во время инициализации. |
| `max_connections` | 200–400 (или меньше с PgBouncer) | Каждое соединение стоит ~10 МБ RAM. При 500 соединений — 5 ГБ только на бэкенды. |
| `wal_buffers` | 16–64 МБ | Ускоряет запись WAL при высокой частоте COMMIT. |
| `checkpoint_timeout` | 15–30 мин | Слишком частые чекпоинты создают всплески I/O во время теста. |
| `checkpoint_completion_target` | 0.9 | Растягивает чекпоинт во времени, снижая пиковые задержки. |
| `max_wal_size` | 4–8 ГБ | Позволяет накопить WAL между чекпоинтами, уменьшая I/O всплески. |
| `synchronous_commit` | `off` (только для бенчмаркинга!) | Убирает `fsync` на каждый COMMIT. **Не используйте в production.** |
| `full_page_writes` | `off` (только для бенчмаркинга!) | Убирает двойную запись страниц при чекпоинте. **Не используйте в production.** |

**Важно:** Сохраните оригинальный `postgresql.conf` перед изменением и восстановите его после теста. Изменения выше допустимы только на изолированном стенде.

### Взаимодействие с WAL и репликацией

pgbench генерирует значительный объем WAL из-за частых UPDATE и INSERT. Если на реплике настроено `wal_keep_size` или потоковая репликация, длительный тест может вызвать **Replica Lag**. Подробнее: [Журнал предзаписи (WAL)](./write_ahead_log.md), [Репликация баз данных](./replication.md).

---

## Кастомные SQL-скрипты

pgbench позволяет писать собственные SQL-сценарии через файлы:

### Пример 1: Точечные selects

```sql
-- custom_select.sql — точечные selects по primary key
\set aid random(1, 10000000)
SELECT abalance FROM pgbench_accounts WHERE aid = :aid;
```

### Пример 2: Смешанная нагрузка

```sql
-- mixed_workload.sql — смешанная нагрузка с динамическими данными
\set aid random(1, 10000000)
\set bid random(1, 10000)
\set tid random(1, 100000)
\set delta random(-5000, 5000)

BEGIN;
UPDATE pgbench_accounts SET balance = balance + :delta WHERE aid = :aid;
UPDATE pgbench_tellers SET balance = balance + :delta WHERE tid = :tid;
UPDATE pgbench_branches SET balance = balance + :delta WHERE bid = :bid;
INSERT INTO pgbench_history (tid, bid, aid, delta, mtime) VALUES (:tid, :bid, :aid, :delta, CURRENT_TIMESTAMP);
END;
```

### Запуск кастомных скриптов

```bash
# Запуск с кастомным скриптом:
pgbench -c 32 -j 8 -T 300 -f custom_select.sql mydatabase

# Смешивание стандартных и кастомных сценариев (веса):
pgbench -c 32 -j 8 -T 300 \
    -f custom_select.sql@70 \
    -f mixed_workload.sql@30 \
    mydatabase
```

### Доступные pgbench-директивы

| Директива | Описание | Пример |
| :--- | :--- | :--- |
| `\set var random(min, max)` | Генерация случайного числа | `\set aid random(1, 10000000)` |
| `\set var int'literal'` | Присвоение переменной | `\set scale 100` |
| `\sleep int' seconds'` | Пауза между запросами | `\sleep 0.5` |
| `\g` | Выполнение накопленного запроса | После нескольких SQL-строк |

---

## Валидация и повторяемость

pgbench по умолчанию выводит только средние значения. Для SRE-практики недостаточно.

### 1. Прогрев (Warm-up)

Перед замером прогрев Buffer Pool обязателен:

```bash
# Прогрев всех таблиц pgbench
psql -d mydatabase -c "
  SELECT pg_prewarm('pgbench_accounts');
  SELECT pg_prewarm('pgbench_tellers');
  SELECT pg_prewarm('pgbench_branches');
"
```

Первые 2–5 минут теста исключайте из анализа — это "холодный старт".

### 2. Многократные запуски

Запускайте каждый сценарий минимум 3 раза и берите медиану TPS. Стандартное отклонение не должно превышать 5% от среднего.

```bash
for i in 1 2 3; do
  pgbench -c 32 -j 8 -T 600 mydatabase | tee "run_$i.log"
done
```

### 3. Проверка перцентилей

Основной вывод pgbench не содержит p95/p99. Используйте `--log` и внешний инструмент для расчета:

```bash
pgbench -c 32 -j 8 -T 300 --log --log-prefix=run1 mydatabase
# Анализ latencies:
awk '/^ latency /{print $3}' run1_pgbench_log_*.log | sort -n | awk '{a[NR]=$1} END{print "p95:", a[int(NR*0.95)], "p99:", a[int(NR*0.99)]}'
```

### 4. Проверка Coordinated Omission

pgbench использует Closed Loop модель. При росте Latency автоматически падает RPS, что маскирует реальную пропускную способность. Для точных измерений используйте `--rate` (PostgreSQL 13+) или внешние инструменты с Open Loop моделью.

```bash
# Ограничение скорости 10000 TPS (PostgreSQL 13+)
pgbench -c 50 -j 8 -T 600 --rate=10000 mydatabase
```

---

## Интерпретация вывода

```text
transaction type: <builtin: TPC-B (sort of)>
scaling factor: 100
query mode: simple
number of clients: 50
number of threads: 8
duration: 600 s
number of transactions actually processed: 1456789
latency average = 2.061 ms
initial connection time = 12.345 ms
tps = 24279.816449 (without establishing connection)
```

**На что смотреть:**
- **`tps`** — пропускная способность без учёта времени установки соединения. Сравнивайте с baseline.
- **`latency average`** — средняя задержка. Для более детального анализа используйте `--log`.
- **`initial connection time`** — время установки соединения. Если велико, проверьте настройки `max_connections` и Connection Pooler.
- **`number of transactions actually processed`** — фактически обработанные транзакции. Должно быть близко к ожидаемому (TPS * duration).

---

## Мониторинг во время теста

Откройте мониторинг в отдельных терминалах или собирайте метрики в систему сбора.

### PostgreSQL

```sql
-- Активные запросы и wait events
SELECT pid, state, wait_event, query_start, now() - query_start AS duration
FROM pg_stat_activity
WHERE state != 'idle'
ORDER BY duration DESC;

-- Статистика по базам (транзакции, объем WAL)
SELECT datname, xact_commit, xact_rollback, wal_bytes FROM pg_stat_database;

-- Активность checkpoint'ов
SELECT checkpoints_timed, checkpoints_req, buffers_checkpoint, buffers_clean, maxwritten_clean
FROM pg_stat_bgwriter;

-- Для тестов на реплике:
SELECT client_addr, state, sent_lsn, write_lsn, flush_lsn, replay_lsn, pg_wal_lsn_diff(sent_lsn, replay_lsn) AS lag_bytes
FROM pg_stat_replication;
```

### Операционная система

```bash
# I/O и очередь дисков
iostat -xz 1

# CPU и контекстные переключения
vmstat 1

# Сеть (если pgbench на удаленном хосте)
sar -n DEV 1
```

**Критические пороги:**
- `iowait` > 30% — дисковая подсистема перегружена.
- `load average` > количества ядер — CPU starvation.
- `pg_stat_bgwriter.buffers_checkpoint` растет быстрее `buffers_clean` — чекпоинты слишком частые.

---

## Поиск и устранение неисправностей

### Результаты нестабильны между запусками

**Симптомы:** TPS колеблется более чем на 10% при одинаковых параметрах.
**Причины:**
- Не выполнены прогрев Buffer Pool.
- Checkpoint или autovacuum запустились во время теста.
- Частота CPU не зафиксирована (Turbo Boost / throttle).
**Решение:** фиксируйте `scaling_governor = performance`, исключайте первые 5 минут теста, запускайте минимум 3 раза.

### Высокий initial connection time

**Симптом:** `initial connection time = 500+ мс`.
**Причины:**
- Отсутствует Connection Pooler (PgBouncer).
- `max_connections` исчерпан, новые соединения ставятся в очередь.
- DNS-резолвинг при подключении по имени хоста.
**Решение:** используйте PgBouncer, подключение по IP, увеличьте `max_connections` или уменьшите `-c`.

### Чекпоинтовые всплески во время теста

**Симптомы:** TPS периодически проседает каждые `checkpoint_timeout` минут.
**Причины:** `checkpoint_timeout` слишком мал для длительности теста, или `max_wal_size` исчерпан.
**Решение:** увеличьте `checkpoint_timeout` до 30–60 мин и `max_wal_size` до 8–16 ГБ для длительных тестов.

### WAL-насыщение и Replica Lag

**Симптомы:** Рост `pg_stat_replication.lag_bytes`, диск с WAL заполняется.
**Причины:** pgbench генерирует WAL быстрее, чем реплика потребляет или архиватор сбрасывает.
**Решение:** увеличьте `wal_keep_size`, отключите archival на время теста, или используйте тестовый стенд без репликации.

### pgbench становится узким местом

**Симптомы:** CPU на хосте клиента загружен >80%, TPS не растет с увеличением `-c`.
**Причины:** pgbench не хватает потоков `-j` для обработки результатов.
**Решение:** увеличьте `-j` до количества ядер CPU клиента, вынесите pgbench на отдельный хост.

---

## Ограничения

- **TPC-B, не TPC-C:** pgbench имитирует TPC-B (упрощенный профиль), а не полноценный TPC-C. Для TPC-C используйте [HammerDB](./hammerdb.md).
- **Только PostgreSQL:** Не работает с другими СУБД.
- **Перцентили не в основном выводе:** pgbench не сообщает p95/p99 в стандартном выводе. Для детального анализа используйте `--log` и пост-обработку.
- **Closed Loop модель:** При росте Latency автоматически падает RPS. Для Open Loop используйте `--rate` (PostgreSQL 13+) или внешние инструменты.
- **Нет встроенного прогресс-бара:** Используйте `-P 1` для периодического вывода TPS.
- **Одна база за раз:** Не поддерживает параллельное тестирование нескольких баз в одном процессе.
- **Default fillfactor=100:** При инициализации pgbench создает таблицы с `fillfactor=100`, что вызывает Page Splits при интенсивных UPDATE. Укажите `--fillfactor=80` для write-heavy сценариев.
- **Длительная инициализация:** Для SF > 1000 инициализация может занимать десятки минут. Используйте `-j` для параллельного создания таблиц.

---

## Best Practices

1.  **Никогда не тестируйте production без оговорок:** Используйте read-only реплику (`-S`) или выделенное окно обслуживания. Even read-only тест создает нагрузку на CPU и диски.
2.  **Изоляция:** Запускайте pgbench на отдельном хосте. Если это невозможно — используйте `taskset` и `nice` для изоляции CPU.
3.  **Объем данных:** Scale factor должен обеспечивать размер данных > 2× RAM сервера. Иначе вы тестируете кэш, а не дисковую подсистему.
4.  **Прогрев:** Всегда прогревайте Buffer Pool перед тестом. Исключайте первые 2–5 минут из анализа.
5.  **Повторяемость:** Запускайте минимум 3 раза, берите медиану. Длительность Steady State — минимум 15 минут (30 мин предпочтительнее).
6.  **Фиксация конфигурации:** Сохраняйте `postgresql.conf` и версию ПО перед каждым тестом. Восстанавливайте конфигурацию после завершения.
7.  **Мониторинг WAL:** Следите за `wal_bytes` в `pg_stat_database` и `sent_lsn`/`replay_lsn` на репликах. Длительный pgbench-тест может вызвать Replica Lag.
8.  **Используйте `--latency-limit` (PostgreSQL 13+):** Автоматически прерывает транзакции, превышающие порог. Помогает выявить tail latency без пост-обработки логов.

---

## Дополнительная информация

### См. также

- **[Нагрузочное тестирование СУБД](./benchmarking.md)** — общая методология, подготовка среды, интерпретация результатов.
- **[Ключевые концепции производительности](./database_performance_concepts.md)** — теория TPS, Latency, USE-метод.
- **[sysbench](./sysbench.md)** — кросс-СУБД бенчмаркинг (MySQL, PostgreSQL, MariaDB).
- **[HammerDB](./hammerdb.md)** — кросс-СУБД бенчмаркинг (TPC-C/TPC-H).
- **[Журнал предзаписи (WAL)](./write_ahead_log.md)** — как pgbench-нагрузка увеличивает объем WAL и влияет на архивацию.
- **[Репликация баз данных](./replication.md)** — влияние нагрузочного тестирования на задержку репликации.
