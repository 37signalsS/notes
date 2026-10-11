# Runbook: алерты → диагностика → действие

**Актуально для:** Apache Cassandra 4.0/5.0.x / ScyllaDB 2026.x

## Определения

| Термин | Определение |
| :--- | :--- |
| Runbook | Документ «алерт → диагностика → действие → валидация → эскалация» для типовых инцидентов |
| SLO / SLI | Целевой уровень обслуживания / индикатор, его измеряющий (latency, доступность, ошибки) |
| Эскалация | Передача инцидента на уровень выше (вендор, команда БД) с пакетом диагностики |
| Blast radius | Масштаб воздействия действия: сколько узлов/клиентов затронуто |

Пороги алертов и метрики — в [Мониторинге](./monitoring.md); исключения и их слои — в [Troubleshooting](./troubleshooting.md).

## Структура реакции на инцидент

1. **Классифицировать:** масштаб (один узел / DC / кластер), тип операции (чтение/запись), тип ошибки (см. методологию в [Troubleshooting](./troubleshooting.md)).
2. **Диагностировать** по алерту (ниже) — собрать данные **до** рестарта узла.
3. **Действовать** — минимальный blast radius: один узел за раз, throttling при обслуживании.
4. **Валидировать** — команда проверки из раздела алерта.
5. **Эскалировать** — с пакетом диагностики (см. [Troubleshooting](./troubleshooting.md)).

Правило: меняйте **один параметр за раз** и фиксируйте до/после (см. [Тюнинг](./performance.md)).

## Предпосылки и подготовка

Онлайн-реакция требует собранного контекста. Перед вмешательством убедитесь, что готово:

- **Доступ:** SSH на узлы кластера; JMX-аутентификация для `nodetool` (`-u <user> -pw <пароль>`, см. [Безопасность](./security.md)); `cqlsh` с учётными данными.
- **Инструменты на узлах:** `nodetool`, `ss`, `iostat`, `df`. Для ScyllaDB — `scylla-doctor` (собирает `.vitals.json` + архив логов) и `scyllatop` (per-shard диагностика — не `top`, ScyllaDB многопоточна per-shard, см. [Troubleshooting](./troubleshooting.md)).
- **Пути:** каталоги данных (`/var/lib/cassandra`, `/var/lib/scylla`) и логов — `/var/log/cassandra/system.log`, `/var/log/scylla/scylla.log` (в production — `journalctl`); сервисы `cassandra`/`scylla-server` под управлением systemd.
- **Конфигурация:** `cluster_name`, seed-узлы, `listen_address`/`rpc_address`/`broadcast_address` — в `cassandra.yaml`/`scylla.yaml` ([Установка](./installation.md)).
- **Связность и часы:** NTP на всех узлах (`ntpstat`/`chronyc tracking`); проверка сети между нодами (firewall, MTU).
- **Контекст:** SLO/SLI и пороги алертов (см. [Мониторинг](./monitoring.md)); текущее окно ТО.

Собирать диагностику **до** рестарта: рестарт стирает состояние очередей, thread/heap dump и streaming-прогресс.

## Сценарии

### 1. Узел DOWN (алерт `up` / `nodetool status` — DN)

**Диагностика:**

```bash
nodetool status                    # какие узлы DN, в каком DC
nodetool describecluster           # недостижимые узлы, версии схемы
journalctl -u scylla-server -n 100 # или tail /var/log/cassandra/system.log
df -h /var/lib/cassandra /var/lib/scylla   # диск заполнен?
```

**Действие:** по причине — освободить место, поднять узел, исправить конфиг. Если узел мёртв надолго — `nodetool removenode <host_id>` (данные стримятся с реплик) или replace на новом узле (см. [Обслуживание](./operations.md)).

**Валидация:** `nodetool status` — все узлы `UN`; hints доставлены (`nodetool listpendinghints` — пусто).

**Эскалация:** Cassandra — `system.log` + `gc.log` + heap dump; ScyllaDB — `scylla-doctor` vitals + логи.

### 2. Диск заполняется

**Диагностика:**

```bash
df -h /var/lib/cassandra /var/lib/scylla
nodetool compactionstats     # backlog compaction
nodetool listsnapshots       # снапшоты (в т.ч. после scrub/verify)
nodetool listpendinghints    # hints (Cassandra 4.1+)
```

**Действие:** удалить ненужные снапшоты (`nodetool clearsnapshot`), поднять throughput compaction (`nodetool setcompactionthroughput`), добавить место. При критическом заполнении Cassandra может отказывать в записи, ScyllaDB прекращает принимать записи.

**Валидация:** `df -h` — место освобождено; `nodetool compactionstats` — backlog снижается.

**Профилактика:** алерты на свободное место и compaction backlog (см. [Мониторинг](./monitoring.md)).

### 3. Рост latency / timeouts (алерт P99, `coordinator_*_timeouts`)

**Диагностика:**

```bash
nodetool tpstats          # PendingTasks растёт? Dropped Messages > 0?
nodetool compactionstats  # backlog compaction?
nodetool gcstats          # паузы GC (Cassandra)
nodetool tablehistograms <ks> <table>   # tombstones, SSTables на чтение
iostat -x 1               # диск в потолке (%util, await)?
```

**Действие:** найти узкое место (диск / compaction / GC / tombstones / перегрузка) и устранить его. Простое повышение таймаутов маскирует проблему. ScyllaDB: `scylla_database_sstable_read_queue_overloads > 0` — перегрузка чтениями.

**Валидация:** latency вернулся к SLO; `nodetool tpstats` — PendingTasks стабильно < 50, Dropped = 0.

### 4. `UnavailableException` (алерт `coordinator_*_unavailable`)

**Диагностика:** `nodetool status` — какие реплики DOWN; `RF` keyspace соответствует числу узлов в DC?

**Действие:** восстановить реплики (bootstrap/replace/rebuild — см. [Обслуживание](./operations.md)); временно снизить consistency level (с потерей гарантий `R + W > RF`).

**Валидация:** `nodetool status` — все реплики `UN`; ошибки прекратились.

### 5. Compaction backlog (алерт `PendingCompactions` / `scylla_compaction_manager_backlog`)

**Диагностика:** `nodetool compactionstats`; `nodetool tablestats` — число SSTables на таблицу; какая keyspace/таблица растёт.

**Действие:** поднять `nodetool setcompactionthroughput` (если диск позволяет); проверить стратегию compaction под паттерн нагрузки (см. [Обслуживание](./operations.md)); при TWCS — `nodetool sstableexpiredblockers`.

**Валидация:** `nodetool compactionstats` — pending снижается; `LiveSSTableCount` стабилизировался.

### 6. Tombstone warnings (алерт `TombstoneWarnings`)

**Диагностика:** формат записи в логе и пороги — в [Тюнинг → Диагностика Tombstones](./performance.md#диагностика-tombstones); `nodetool tablehistograms`.

**Действие:** исправить модель данных (временные ряды — TWCS), запустить repair, при гарантии частого repair — уменьшить `gc_grace_seconds`. **Не** повышать `tombstone_failure_threshold` — это маскирует проблему.

**Валидация:** предупреждения исчезли из логов; `TombstoneScannedHistogram` — хвост не растёт.

### 7. Паузы GC > 500 мс (Cassandra)

**Диагностика:** GC-лог (`gc.log`), `nodetool gcstats`, размер heap (`nodetool info`).

**Действие:** heap ≤ 31GB, G1 для > 12GB, `-Xms = -Xmx`, `-Xmn` не задавать при G1; тюнинг G1 — в [Тюнинг](./performance.md).

**Валидация:** `nodetool gcstats` — паузы < 500 мс.

### 8. OOM / падение узла

**Диагностика:** heap dump в `CASSANDRA_HEAPDUMP_DIR` (на 5.0.4+ по умолчанию — лог-каталог: дамп размером с heap может заполнить ФС — указывайте ФС с запасом); ScyllaDB — core dump в `/var/lib/scylla/coredump`.

**Действие:** найти причину (heap, row cache, prepared cache, большой partition); Cassandra при OOM завершается принудительно (`kill -9`) — supervisor/systemd перезапускает узел.

**Валидация:** узел `UN`, OOM не повторяется при той же нагрузке.

### 9. Repair завершается ошибкой

**Диагностика:** `nodetool status` (недоступные узлы), сеть, диск; ScyllaDB: не выполнять topology-операции и изменения схемы во время repair.

**Действие:** повторить; при систематических ошибках — сегментация repair (Cassandra Reaper: `-st`/`-et`, job threads).

**Валидация:** `nodetool repair_admin summarize-repaired` (Cassandra 4.0+); метрика `PercentRepaired` растёт. ScyllaDB: `sctool status` / метрика `scylla_manager_repair_progress`.

### 10. Записи дублируются после таймаута

**Причина:** повтор неидемпотентного запроса на стороне приложения или драйвера.

**Действие:** идемпотентность на стороне приложения (условная вставка, фиксированный timestamp) или `IF NOT EXISTS` (LWT — дорого); драйвер — `setIdempotent(true)` для безопасных запросов (см. [Драйверы](./drivers.md)).

**Валидация:** дубликаты не появляются при повторных таймаутах в тесте.

### 11. Узел завис в bootstrap / JOINING (stuck streaming)

**Диагностика:**
```bash
nodetool netstats          # режим узла, прогресс/скорость streaming
nodetool tpstats           # Blocked в пулах?
nodetool describecluster   # версии схемы, недостижимые узлы
iostat -x 1                # диск в потоле (%util, await)?
```

**Причина:** заблокированная потоковая передача — сеть между узлами (firewall, MTU), дисковая перегрузка реплики-источника, либо одновременная topology-операция (bootstrap + repair + rebuild).

**Действие:** дождаться отведения или приостановить через throttling (`nodetool setstreamthroughput`); проверить сеть между узлами; не запускать одновременно bootstrap, repair и rebuild. Если узел завис надолго — остановить, очистить partially-streamed данные и начать `replace` на новом узле (см. [Обслуживание → Жизненный цикл узла](./operations.md#жизненный-цикл-узла-node-lifecycle)).

**Валидация:** `nodetool status` — узел `UN`; `nodetool netstats` — без pending streaming.

### 12. Schema disagreement (несколько версий схемы)

**Диагностика:**
```bash
nodetool describecluster    # schema versions: должна быть одна; несколько — disagreement
cqlsh -e "DESCRIBE SCHEMA;" # DDL всех keyspaces
```

**Причина:** схема ещё не распределилась по gossip после `ALTER`/`CREATE`; либо узел с отличающейся версией схемы перезапущен вне очереди во время rolling upgrade.

**Действие:** дождаться сходимости (schema versions сходятся автоматически); если не сходится — перезапустить узел с «чужой» версией; не менять схему во время rolling upgrade (см. [Миграция и upgrade](./upgrade-migration.md)).

**Валидация:** `nodetool describecluster` — одна версия схемы на всех узлах; `cqlsh -e "DESCRIBE SCHEMA;"` проходит без ошибок.

### 13. Hints backlog (накопление hints)

**Диагностика:**
```bash
nodetool listpendinghints   # Cassandra 4.1+: файлы/хосты hints
nodetool statushandoff      # включена/выключена доставка hints
nodetool getmaxhintwindow   # окно хранения (дефолт 3 часа)
# ScyllaDB: метрика scylla_hints_manager_send_errors
```

**Причина:** реплика была down дольше `max_hint_window` (3 ч) — hints удаляются, консистентность восстанавливается только repair; либо узел up, но не доставляет hints (network, узкое место).

**Действие:** восстановить реплики → `nodetool repair` (чаще `gc_grace_seconds`); при захвате диска — `nodetool truncatehints` (только после подтверждения, что реплики восстановлены); приостановить/возобновить доставку: `nodetool pausehandoff`/`nodetool resumehandoff`. Подробности — в [Troubleshooting → Hints](./troubleshooting.md#hints-hinted-handoff).

**Валидация:** `nodetool listpendinghints` — пусто; `nodetool statushandoff` — включена; метрика `scylla_hints_manager_send_errors` не растёт.

### 14. Zombie data / clock skew (воскрешение удалённых данных)

**Диагностика:**
```bash
ntpstat              # синхронизация часов
chronyc tracking     # drift
date                 # на каждом узле — сравнить
# удалённая запись снова видна после восстановления узла
```

**Причина:** узел был down дольше `gc_grace_seconds` (дефолт 10 дней) — tombstone не доставлен при recovery, запись «воскрешается» при следующем repair/чтении. Рассинхрон часов усиливает проблему: LWW-разрешение конфликтов выбирает более старую запись.

**Действие:** `nodetool repair` чаще `gc_grace_seconds`; NTP на всех узлах обязателен; не уменьшать `gc_grace_seconds` без гарантии частого repair. Подробности — в [Troubleshooting → Zombie data и clock skew](./troubleshooting.md#zombie-data-и-clock-skew).

**Валидация:** удаляемая запись больше не возвращается после восстановления узла; `date`/`chronyc` — синхронизированы на всех узлах.

## SLO/SLI для Cassandra/ScyllaDB

| SLI | Целевое значение (стартовая точка) | Источник |
| :--- | :--- | :--- |
| Доступность записи/чтения | 99.9%+ | успешные операции / все операции |
| P99 latency чтения | < 20 мс (калибровать под SLA) | `ClientRequest.*.Latency` / `scylla_storage_proxy_coordinator_read_latency` |
| P99 latency записи | < 50 мс (калибровать под SLA) | `ClientRequest.*.Latency` / `scylla_storage_proxy_coordinator_write_latency` |
| Таймауты / unavailable | 0 | `coordinator_*_timeouts` / `*_unavailable` |
| Доля repaired-данных | ≈ 100% | `PercentRepaired` |

Калибруйте пороги под SLA и нагрузку — стартовые точки, не универсальные истины.

## Очистка после инцидента

```bash
nodetool clearsnapshot            # снапшоты после scrub/verify
rm /var/log/cassandra/cassandra-*-pid*.hprof   # heap dump (может быть размером с heap)
```

## См. также

- **[Мониторинг и observability](./monitoring.md)** — метрики, пороги алертов.
- **[Поиск и устранение неисправностей](./troubleshooting.md)** — методология, исключения, диагностический bundle.
- **[Тюнинг производительности](./performance.md)** — GC, tombstones, антипаттерны.
- **[Обслуживание и эксплуатация](./operations.md)** — repair, topology-операции.
- **[Миграция и upgrade](./upgrade-migration.md)** — rolling upgrade, изменение схемы.
- **[Драйверы](./drivers.md)** — idempotence, retry.
- **[Disaster Recovery](../../Concepts/disaster_recovery.md)** — RPO/RTO, эскалация.
