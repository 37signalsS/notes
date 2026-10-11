# Multi-DC и аварийное восстановление (DR)

**Актуально для:** Apache Cassandra 4.0/5.0.x / ScyllaDB 2026.x

## Определения

| Термин | Определение |
| :--- | :--- |
| **DC (Data Center)** | Логическая группа узлов в одной сетевой зоне (low-latency); один DC = одна отказоустойчивая домена |
| **NetworkTopologyStrategy** | Стратегия репликации с явным RF per DC — обязательно для multi-DC |
| **Snitch** | Компонент, сообщающий кластеру сетевую топологию (DC/rack) для маршрутизации реплик; production-стандарт — `GossipingPropertyFileSnitch` |
| **LOCAL_QUORUM** | Кворум реплик в локальном DC — золотой стандарт записи/чтения в geo-распределённых кластерах |
| **EACH_QUORUM** | Кворум в **каждом** DC — строгая меж-DC согласованность ценой доступности и latency |
| **RPO / RTO** | Максимально допустимая потеря данных / время восстановления (теория — [Disaster Recovery](../../Concepts/disaster_recovery.md)) |
| **Switchover** | Плановое переключение трафика на другой DC (обслуживание, миграция) |
| **Failover** | Аварийное переключение на другой DC при отказе |
| **Tablet** | Единица распределения данных в ScyllaDB (замена vNodes с 2024.x); автоматическая балансировка без ручного перебалансирования |
| **Strongly Consistent Table** | Таблица ScyllaDB 2026.2+ с глобальной согласованностью через Raft per tablet; по умолчанию отключена |
| **Parallel bootstrap** | Параллельный ввод новых узлов в кластер (ScyllaDB 2026.2+ / Operator 1.22+); ускоряет расширение DC |

## Архитектура и сетевые требования

### Топология и snitch

Каждый узел должен знать свой DC/rack. Production-стандарт — `GossipingPropertyFileSnitch` с файлами `cassandra-rackdc.properties` (Cassandra) или `scylla.yaml` (ScyllaDB). При добавлении нового DC — создать файл конфигурации с верными `dc=` и `rack=` **до** первого запуска; иначе gossip распространит неверные метаданные и потребуется manual unmarshall/cleanup.

**Важно:** имена DC чувствительны к регистру и должны совпадать с именами в `NetworkTopologyStrategy` (например, `DC1` ≠ `dc1`).

### Сеть и производительность канала

Меж-DC канал — узкое место при репарации, streaming и commitlog archive. Требования:

- **Latency:** для async-репликации приемлема высокий RTT; для Strongly Consistent Tables или EACH_QUORUM — RTT напрямую влияет на latency коммита.
- **Bandwidth:** repair одного узла при RF=3 может занять весь канал; throttle обязателен.
- **MTU:** единый MTU на всём пути между DC; фрагментация приведёт к ретраям и разрывам streaming.
- **Loss:** потери пакетов на уровне >1% деградируют gossip и streaming; требует фикса на сетевом оборудовании.

### Шифрование и firewall

- **Internode encryption:** `internode_encryption: dc` (меж-DC) или `all` (включая intra-DC). Для mixed-mode (старые/новые узлы) используйте `dc` — это не шифрует intra-DC, что упрощает ротацию сертификатов.
- **Порты:**
  - `7000/tcp` — internode (Cassandra/ScyllaDB unencrypted)
  - `7001/tcp` — internode TLS
  - `9042/tcp` — native transport (CQL)
  - `9142/tcp` — native transport TLS
  - `7199/tcp` — JMX (Cassandra; ScyllaDB используетPrometheus endpoint)
  - `9180/tcp` — Prometheus metrics (ScyllaDB)
  - `10000/tcp` — Scylla Manager agent
- **Firewall:** разрешайте только traffic между DC на internode-порты; CQL-порт открыт только для приложений.

### ScyllaDB 2026.2+: Strongly Consistent Tables

По умолчанию Cassandra/ScyllaDB — eventual consistency; реплики могут расходиться на короткое время. ScyllaDB 2026.2+ предлагает Strongly Consistent Tables (Raft per tablet), которые дают глобальную линейзуемость. **Для multi-DC это означает:**
- Возможность отказаться от EACH_QUORUM при сохранении сильных гарантий.
- Повышенный RTT на запись (Raft quorum across replicas, включая remote DC при RF>1).
- Включение: `WITH CONSISTENCY = 'strong'` (или аналогичный синтаксис; проверяйте release notes конкретной версии).
- **Ограничение:** не все операции совместимы с LWT и TTL; тестируйте на нагрузке перед production.

## Как устроена multi-DC топология

**Репликация:** `NetworkTopologyStrategy` задаёт RF отдельно для каждого DC:

```sql
CREATE KEYSPACE my_app WITH replication = {
    'class': 'NetworkTopologyStrategy',
    'dc1': 3,
    'dc2': 3
};
```

**Маршрутизация:** snitch (`GossipingPropertyFileSnitch`) сообщает каждому узлу топологию DC/rack; координатор выбирает реплик в нужном DC. Между DC — асинхронная репликация: запись с `LOCAL_QUORUM` в dc1 реплицируется в dc2 без блокировки клиента.

**Уровни согласованности в multi-DC** (полная таблица — в [Обслуживании](./operations.md)):

| Уровень | Гарантия | Когда |
| :--- | :--- | :--- |
| `LOCAL_QUORUM` | кворум в локальном DC | золотой стандарт: нет меж-DC latency |
| `LOCAL_ONE` | 1 реплика в локальном DC | высокая доступность; данные могут быть stale |
| `QUORUM` | кворум по всему кластеру | редко: latency растёт с числом DC |
| `EACH_QUORUM` | кворум в каждом DC | строгая меж-DC согласованность; низкая доступность |

**Меж-DC трафик:** throttle через `inter_dc_stream_throughput_outbound_megabits_per_sec` (streaming) и `nodetool setrpcthroughput` (RPC); шифрование — `internode_encryption: dc` или `all` (см. [Безопасность](./security.md)).

**Важно:** Cassandra/ScyllaDB **не имеют встроенного автоматического failover между DC** — переключение трафика выполняется на уровне инфраструктуры (load balancer) или приложения. Cross-DC failover в драйвере выключен по умолчанию (`dc-failover.max-nodes-per-remote-dc = 0`) — см. [Драйверы](./drivers.md).

## Практические сценарии

### Добавление нового DC в существующий кластер

1. Подготовить узлы нового DC: snitch с новым именем DC, seeds из существующего DC, единый MTU.
2. Обновить репликацию keyspace:

```sql
ALTER KEYSPACE my_app WITH replication = {
    'class': 'NetworkTopologyStrategy',
    'dc1': 3,
    'dc2': 3          -- новый DC
};
```

3. Запустить новые узлы. Для **vnode keyspaces (Cassandra)** — `nodetool rebuild <source-dc-name>` на каждом узле. Для **tablet keyspaces (ScyllaDB 2024.x+)** — `nodetool rebuild` работает только для vnode keyspaces; для tablets используйте `nodetool cluster repair` или включите RBNO (Repair Based Node Operations) — с 5.4 включён по умолчанию и использует repair для потоковой передачи данных.
4. ScyllaDB 2026.2+ с Operator 1.22+: можно включить `enableParallelNodeOperations` для параллельного bootstrap.
5. После bootstrap — `nodetool cleanup` на узлах старого DC, потерявших диапазлы.
6. Проверить: `nodetool status` — все узлы `UN`, RF per DC по плану, `nodetool netstats` — нет «Joining»/`?` статусов.
7. **Перед удалением старого DC:** снизить RF в keyspace, выполнить `nodetool cleanup` на всех узлах старого DC, убедиться в отсутствии `%` (draining) узлов.

### Стратегии DR по RPO/RTO

| Стратегия | RPO | RTO | Механизм |
| :--- | :--- | :--- | :--- |
| Backup offsite (снапшоты + commitlog archive) | минуты–часы | часы | restore из бэкапа в новом DC/регионе (см. [Бэкап](./backup-recovery.md)) |
| Async replica в другом DC | секунды | минуты | promote/переключение трафика на DC2 (инфраструктурный failover) |
| Sync-репликация между DC (`EACH_QUORUM`) | 0 | минуты | почти всегда неоправдана: latency коммита + RTT между DC |

Стандарт: **async replica в другом DC + бэкап offsite** — баланс RPO/RTO без штрафа latency.

### Switchover (плановый)

1. Убедиться, что DC2 полностью синхронизирован (repair актуален, `PercentRepaired` ≈ 100%; для ScyllaDB Manager — `sctool status`).
2. Переключить трафик приложения на DC2 (load balancer / смена contact points; приложение должно быть collocated с DC — `local-datacenter` в драйвере).
3. Выполнить обслуживание DC1.
4. Обратный switchover после восстановления DC1.

### Failover (аварийный)

1. Подтвердить отказ DC (не сетевой сбой: `nodetool status`, мониторинг; проверьте `internode_encryption` и firewall).
2. Переключить трафик на DC2 на уровне инфраструктуры.
3. При записи с `LOCAL_QUORUM` в DC2 — данные доступны; расхождения с DC1 устраняются repair после восстановления.
4. **Не** полагаться на `ConsistencyDowngradingRetryPolicy` как на failover — он деградирует guarantees (см. [Драйверы](./drivers.md)).

## Эксплуатация и команды

### Базовые команды топологии

```bash
# Состояние узлов по DC
nodetool status
# → Datacenter: dc1
#   Status=Up/Down
#   |/ State=Normal/Leaving/Joining/Moving

# Топология и rack
nodetool gossipinfo | grep -E "^DC:|^RAC:"
nodetool describecluster
```

### Меж-DC соединения и трафик

```bash
# Активные соединения между узлами (включая remote DC)
nodetool netstats

# Просмотр и изменение throttle streaming (меж-DC)
nodetool getstreamthroughput
nodetool setrpcthroughput <megabits_per_sec>

# RPC-очереди на coordination
nodetool tpstats | grep -E "Messages|Dropped"
```

### Добавление и удаление DC

```bash
# Для vnode keyspaces (Cassandra) / старых ScyllaDB
nodetool rebuild <source-dc-name>

# Для tablet keyspaces (ScyllaDB 2024.x+); RBNO использует repair
nodetool cluster repair <keyspace> -dc <source-dc-name>

# После потери диапазлов (старый DC)
nodetool cleanup <keyspace>
nodetool cleanup <keyspace> -st <start-token> -et <end-token>
```

### Repair и планирование

```bash
# Repair конкретного DC (обязательно для multi-DC при fsync/commitlog archive)
nodetool repair -dc dc1 -dcpar

# Incremental repair (Cassandra 4.0+; ScyllaDB — через Scylla Manager)
nodetool repair -inc -dc dc1

# Параллельный repair (ScyllaDB Manager / Reaper)
sctool repair start --keyspace my_app --dc dc1 --parallel 4
```

**Правило:** repair должен проходить чаще `gc_grace_seconds` (дефолт 10 дней). При commitlog archive для PITR — repair должен быть актуален, иначе archive будет содержать мутации, удалённые на репликах.

### ScyllaDB Manager (ScyllaDB 2026.x)

```bash
# Проверка статуса агента
sctool status

# План repair
sctool repair task create --keyspace my_app --interval 24h --dc dc1 --dc dc2

# Бэкап
sctool backup create --keyspace my_app --location s3:bucket/path
```

## Валидация

| Что проверяем | Команда / сигнал | Ожидание |
| :--- | :--- | :--- |
| Топология | `nodetool status` (по DC) | узлы `UN` в каждом DC, RF per DC по плану |
| Snitch | `nodetool gossipinfo` / `nodetool describecluster` | правильные DC/rack у всех узлов |
| Меж-DC соединения | `nodetool netstats` | соединения `open` между узлами разных DC, нет `?` |
| Schema agreement | `nodetool describecluster` | `Schema versions` совпадают; при расхождении — `nodetool flush` + `nodetool repair` на координаторах |
| Меж-DC репликация | запись с `LOCAL_QUORUM` в DC1, чтение с `LOCAL_ONE` в DC2 | данные видны (async — с задержкой); для strict freshness — `LOCAL_QUORUM` в DC2 |
| Repair lag | `nodetool repair_admin summarize-repaired`; `PercentRepaired` (ScyllaDB Manager) | ≈ 100% перед switchover |
| Throttling | `nodetool getstreamthroughput` | меж-DC streaming ограничен; узел не занимает весь канал |
| Encryption | `openssl s_client -connect <node>:9142` | сертификат выдан на DC; CN/SAN корректны |
| Clock skew | `nodetool info` → `Load` / `Gossip active since`; сравнить `date` на узлах | расхождение < 1 сек; при skew — NTP ( Chrony / `systemd-timesyncd` ) |

## Безопасность меж-DC трафика

- **Шифрование:** `internode_encryption: dc` или `all`. `dc` — шифрует только меж-DC трафик, оставляя intra-DC открытым (удобно для mixed clusters). `all` — шифрует всё, включая loopback внутри DC (больше overhead).
- **Сертификаты:** используйте отдельный CA или sub-CA для каждого DC; при компрометации DC можно отозвать только его сертификаты.
- **Аудит:** ScyllaDB Enterprise (2024.2+) поддерживает audit log в `audit.audit_log` таблице. Для multi-DC — реплицируйте `system_auth` и audit keyspace через `NetworkTopologyStrategy` RF=3 (см. [Безопасность](./security.md)).
- **system_auth:** в multi-DC обязательно `NetworkTopologyStrategy` RF ≥ 3, иначе отказ одной реплики = отказ авторизации.

## Мониторинг и observability

**Ключевые метрики multi-DC:**
- **Repair lag:** время с последнего успешного repair per DC. Должно быть < `gc_grace_seconds` / 2.
- **Streaming throughput:** `inter_dc_stream_throughput_outbound_megabits_per_sec` и фактические `bytes_sent` на интерфейсе.
- **Pending hints:** `hinted_handoff_pending` (ScyllaDB) / `HintedHandoffManager` (Cassandra). Высокое значение = медленная доставка в remote DC.
- **Cross-DC latency:** если используете Prometheus, агрегируйте `cassandra_storage_proxy_coordinator_write_latency` и `read_latency` по label `datacenter` (если экспортируется).
- **Schema agreement:** время в `schema_agreement`; долгий converge = проблема gossip или сетевых partitions.

**Алерты (пример):**
- `PercentRepaired < 95%` более чем на одном DC.
- `repair_lag_seconds > 0.5 * gc_grace_seconds`.
- `hinted_handoff_pending` растёт > 5 мин без снижения.
- `nodetool netstats` показывает `?` соединения между DC > 30 сек.

## Поиск и устранение неисправностей

| Симптом | Вероятные причины | Действия |
| :--- | :--- | :--- |
| `UnavailableException` при `LOCAL_QUORUM` | живых реплик в DC меньше кворума | `nodetool status` по DC; восстановить реплики (rebuild/replace) |
| Stale reads в DC2 | async-репликация отстаёт | проверить меж-DC сеть и throttling; repair; проверьте `inter_dc_stream_throughput_outbound_megabits_per_sec` |
| Cross-DC трафик при `LOCAL_*` запросах | `dc-failover` включён с `allow-for-local-consistency-levels`, или LBP без `local-datacenter` | выключить dc-failover для LOCAL_* уровней; задать `local-datacenter` (см. [Драйверы](./drivers.md)) |
| Узел нового DC не bootstrap'ится | неверное имя DC в snitch, seeds недоступны, MTU mismatch | `nodetool describecluster`; логи запуска (см. [Troubleshooting](./troubleshooting.md)) |
| Repair между DC медленный | узкий канал, нет throttling, repair `-st`/`-et` слишком широкие | `inter_dc_stream_throughput_outbound_megabits_per_sec`, `-dc`/`-dcpar` опции repair; сузьте token range |
| Schema disagreement между DC | gossip partition, устаревший `system_schema` на координаторе | `nodetool flush` на всех узлах; `nodetool repair` system keyspace; проверьте firewall на internode-портах |
| Clock skew > 1 сек | NTP не настроен или `system_clock_skew` большой | Настройте Chrony / `systemd-timesyncd`; проверьте `date` и `timedatectl` на всех узлах |
| `nodetool rebuild` не работает (ScyllaDB tablets) | keyspace использует tablets, а rebuild поддерживает только vnodes | Используйте `nodetool cluster repair` или включите RBNO; для миграции tablets — `nodetool tablet migration` |

## Рекомендации

- **`LOCAL_QUORUM` для записи и чтения** в geo-распределённых кластерах; `EACH_QUORUM` — только при жёстком требовании меж-DC консистентности.
- **RF per DC ≥ 3** — переживает отказ одного узла в DC при кворуме.
- **Async replica + offsite-бэкап** — стандартная DR-стратегия; sync между DC почти всегда неоправдан.
- **Failover — инфраструктурный**, не на уровне драйвера: `dc-failover` выключен по умолчанию не случайно.
- **Repair регулярно** (чаще `gc_grace_seconds`) — перед switchover проверяйте `PercentRepaired` / `repair_admin summarize-repaired`.
- **Throttle меж-DC трафик:** `inter_dc_stream_throughput_outbound_megabits_per_sec` и `nodetool setrpcthroughput` — без этого repair/streaming вытеснит клиентский трафик.
- **Шифруйте internode-трафик:** `internode_encryption: dc` минимизирует overhead, но защищает меж-DC канал.
- **Schema-операции откатывайте с CAUTION:** `ALTER KEYSPACE` / `ALTER TABLE` распространяются через gossip; при partition schema может зависнуть на части узлов.
- **Теория DR и RPO/RTO** — [Disaster Recovery](../../Concepts/disaster_recovery.md); расчёт ёмкости для DC — [Capacity Planning](./capacity-planning.md).

## См. также

- **[Обслуживание и эксплуатация](./operations.md)** — уровни согласованности, repair, rebuild.
- **[Обзор и моделирование данных](./overview.md)** — snitch, NetworkTopologyStrategy.
- **[Драйверы](./drivers.md)** — `local-datacenter`, cross-DC failover.
- **[Безопасность](./security.md)** — `internode_encryption` между DC, `system_auth` в multi-DC.
- **[Бэкап и восстановление](./backup-recovery.md)** — offsite-бэкап, PITR.
- **[Troubleshooting](./troubleshooting.md)** — диагностика узлов и кластера.
- **[Capacity Planning](./capacity-planning.md)** — расчёт числа узлов и repair-трафика.
- **[Disaster Recovery](../../Concepts/disaster_recovery.md)** — теория RPO/RTO.
