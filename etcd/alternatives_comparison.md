# etcd и альтернативы: сравнение с Consul и ZooKeeper

**Актуально для:** etcd 3.7.x / 3.6.x / 3.5.x; Consul 1.22.x / 2.0.x; ZooKeeper 3.9.x

## Определения

**Distributed coordination service** — сервис, обеспечивающий согласованное разделяемое состояние для распределённых систем: конфигурацию, обнаружение сервисов, распределённые блокировки, выборы лидера. etcd, Consul и ZooKeeper решают эту задачу разными способами.

**Raft** — алгоритм консенсуса (лидер, термины, реплицируемый лог). Используется в etcd и Consul (реализация HashiCorp Raft, общая с Vault и Nomad).

**ZAB (ZooKeeper Atomic Broadcast)** — протокол атомарной рассылки ZooKeeper. По свойствам близок к Raft (лидер + кворум), но это самостоятельный алгоритм, а не Raft.

**MVCC (Multi-Version Concurrency Control)** — многоверсионность: каждая запись получает ревизию, читатель может запросить состояние на прошлую ревизию. Есть в etcd, отсутствует в ZooKeeper и Consul.

**Watch** — поток уведомлений об изменениях ключей. В etcd — нативный поток с историческими интервалами; в ZooKeeper — одноразовые watcher'ы; в Consul — блокирующие запросы (blocking queries) по индексам.

**Session / Lease** — привязка ключа к сроку жизни: у ZooKeeper это session + ephemeral-узлы, у etcd — lease, у Consul — sessions. Позволяет строить обнаружение сервисов и блокировки с автоматической очисткой.

**Znode** — узел иерархического дерева ZooKeeper (аналог файла/каталога). Бывают persistent, ephemeral, sequential.

**CAP** — теорема о выборе между согласованностью и доступностью при разделении сети. Все три системы — CP: при потере кворума запись недоступна.

---

## Основные концепции

### Модель данных и API

- **etcd** — плоское пространство ключей с префиксами (`/registry/pods/...`), без каталогов. Диапазонные чтения по префиксу, транзакции `Txn` с `Compare`/`Then`/`Else`, нативные `Lock`/`Election` RPC, gRPC API + HTTP/JSON gateway.
- **Consul** — три модели данных: `catalog` (реестр узлов и сервисов), KV-хранилище с префиксами и `ModifyIndex` (CAS), и ACL. API REST + DNS-интерфейс (`*.service.consul`). Понимает health checks из коробки.
- **ZooKeeper** — иерархическое дерево znodes. Транзакции — на уровне version checks (CAS-подобно), блокировки и выборы реализуются через рецепты клиентской библиотеки (`Apache Curator`). Собственный бинарный протокол Jute, ограничивающий набор языковых биндингов.

### Консенсус и доступность

- **etcd:** Raft, лидер принимает записи, кворум `(N/2)+1`. Линеаризуемые чтения через Raft; по умолчанию `etcdctl` выполняет линеаризуемые чтения, но допускается serializable (stale) чтение для снижения нагрузки.
- **Consul:** HashiCorp Raft; серверы — `voter`/`learner`, есть Autopilot, ReadIndex для `consistent`-чтений, `stale`-чтения для доступности при потере кворума.
- **ZooKeeper:** ZAB, ensemble из серверов, кворум большинства; чтения обслуживаются любым сервером и по умолчанию могут быть несвежими (`sync()` для барьера свежести). Есть observers — неголосующие узлы для масштабирования чтений.

### Уведомления об изменениях

| Система | Механизм | Особенность |
| :--- | :--- | :--- |
| etcd | Нативный streaming `Watch` | Исторические интервалы ревизий, `WithPrefix`, переподключение с ревизии |
| ZooKeeper | Однократные `watcher` | Срабатывают один раз; требуется переустановка watcher'а после каждого события |
| Consul | Blocking queries / watches | Возврат при изменении `Index`; подписки через `consul watch` или HTTP long-poll |

### Безопасность и модель доступа

- **etcd:** mTLS для клиентского и peer-трафика; RBAC (пользователи, роли, права на префиксы) включается явно (`etcdctl auth enable`), проверка CN клиента в сертификате — с версии 3.2. Токены аутентификации задаются флагом `--auth-token` (по умолчанию `simple`, для кластеров доступен режим `jwt`). Endpoints `/metrics` и `/health` RBAC не защищаются. Подробнее — в [Безопасности etcd](./security.md).
- **Consul:** TLS для серверов и клиентов, шифрование gossip (`encrypt`), ACL на основе токенов, политик, ролей и binding rules. ACL выключены по умолчанию: требуется `acl { enabled = true }` на серверах и `consul acl bootstrap`; рекомендуемая политика — `default_policy = "deny"`. Подробнее — в [ACL Consul](../Consul/consul_acl.md).
- **ZooKeeper:** ACL на уровне каждого znode (схемы `world`, `auth`, `digest`, `ip`), аутентификация — SASL/Kerberos. По умолчанию znode'ы открыты (`world:anyone`) и трафик не шифруется — ensemble, покидающий доверенную сеть, должен работать с SASL и TLS.

---

## Сравнительная таблица

Данные ниже приведены по официальной таблице etcd «etcd versus other key-value stores» (документация etcd 3.6). Таблицу составляет команда etcd, поэтому она смещена в пользу etcd; по Consul она отражает состояние около версии 1.0 и частично устарела (см. примечание после таблицы).

| Свойство | etcd | ZooKeeper | Consul |
| :--- | :--- | :--- | :--- |
| Примитивы координации | Lock RPC, Election RPC, CLI-локи и выборы | Внешние recipes (Curator, Java) | Нативный lock API |
| Линеаризуемые чтения | Да | По умолчанию нет (нужен `sync()`) | Да |
| MVCC (версионность) | Да | Нет | Нет |
| Транзакции | `Compare`, Read, Write | Проверка версий, Write | Compare, Lock, Read, Write |
| Уведомления об изменениях | Исторические и текущие интервалы ключей | Текущие ключи и каталоги | Текущие ключи и префиксы |
| Права пользователей | Роли (RBAC) | ACL | ACL |
| HTTP/JSON API | Да | Нет | Да |
| Реконфигурация членов | Да | > 3.5.0 | Да |
| Максимальный надёжный объём БД | Несколько ГБ | Сотни МБ (иногда несколько ГБ) | Сотни МБ |
| Минимальная задержка линеаризации чтения | Сетевой RTT | Линеаризация чтения отсутствует | RTT + fsync |

**Примечание об актуальности.** Consul с версии 1.0 заметно развился; текущее состояние его KP-хранилища, sessions, ACL и watch-механизмов описано в разделах этой базы `Consul/` — см. [KV-хранилище Consul](../Consul/consul_kv_store.md), [Консенсус Raft в Consul](../Consul/consul_consensus.md), [ACL Consul](../Consul/consul_acl.md). Максимальный надёжный объём БД — не жёсткий предел, а практическая оценка, за которой растут задержки и давление на память.

### Сравнение консенсусных алгоритмов

| Аспект | etcd (Raft) | ZooKeeper (ZAB) | Consul (HashiCorp Raft) |
| :--- | :--- | :--- | :--- |
| Роль лидера | Единый лидер для записи | Единый лидер (leader) | Единый лидер на терм |
| Кворум | `(N/2)+1` | `(N/2)+1` | `(N/2)+1` |
| Неголосующие читатели | Learners (не влияют на кворум) | Observers | Learners (в OSS), non-voters (Redundancy Zones, Enterprise) |
| Хранение лога | WAL + bbolt (B+tree, COW) | Transaction log + snapshot | WAL (с 1.15) + MemDB/FSM |
| Строгие чтения | Линеаризуемые через Raft | Требует `sync()` | ReadIndex для `consistent` |
| Мин. read latency | Network RTT | Линеаризации нет | RTT + fsync |

Общие принципы Raft в etcd разобраны в [Алгоритм Raft](./raft_consensus.md); специфика Consul — в [Консенсус Raft в Consul](../Consul/consul_consensus.md).

### Лимиты на запись и транзакции

| Система | Макс. размер одного значения | Макс. операций в транзакции |
| :--- | :--- | :--- |
| etcd | 1.5 МиБ (`--max-request-bytes`) | 128 (`--max-txn-ops`) |
| Consul | 512 КиБ (`kv_max_value_size`) | 64 (API `/v1/txn`) |
| ZooKeeper | ≈1 МиБ (`jute.maxbuffer`, по умолчанию `0xfffff`) | Пакеты `multi()` ограничены общим объёмом данных ≈1 МиБ |

Лимиты etcd — в [Лимиты и ограничения](./limits_and_constraints.md), лимит размера значения Consul — в [KV-хранилище Consul](../Consul/consul_kv_store.md). Для ZooKeeper документация рекомендует держать данные znode порядка килобайт, а не приближаться к `jute.maxbuffer`. Большие payload'и в координационном хранилище — это рост снапшотов, лога консенсуса и задержек, поэтому лимиты не стоит использовать как целевой размер объекта.

---

## Когда что выбирать

### etcd

- **Хранилище состояния Kubernetes.** etcd — де-факто стандарт для kube-apiserver: линеаризуемые чтения, MVCC (watch с прошлой ревизии — основа informer'ов), компакция.
- **Плоский KV с транзакциями и MVCC.** Конфигурации, feature flags, реестры, распределённые блокировки и лидер-элекция.
- **Когда критичны исторические watch'и и версионность.** Информеры и контроллеры полагаются на возможность дочитать изменения с произвольной ревизии.

### Consul

- **Обнаружение сервисов из коробки.** DNS-интерфейс, health checks, сервисный каталог, multi-DC через WAN gossip и peering.
- **Service mesh и mTLS.** Connect с прозрачным прокси и intentions для авторизации сервис-к-сервису.
- **Функционально полный стек координации.** KV, ACL, health checks, UI — в одном бинарнике. Одна из причин выбрать Consul вместо etcd для не-Kubernetes сервисного окружения.

### ZooKeeper

- **Наследственные системы и экосистема Java.** Kafka (до 4.0), HBase, Solr, Hadoop используют ZooKeeper. Начиная с Kafka 4.0 (март 2025) ZooKeeper удалён из дистрибутива полностью — кластеры 4.x работают только в режиме KRaft (Raft без ZooKeeper).
- **Рецепты Curator.** Если нужны готовые распределённые примитивы на JVM и уже есть ZooKeeper — оставаться на нём дешевле, чем мигрировать.
- **Новые внедрения под KV-задачи** официальная документация etcd не рекомендует: меньше языковых биндингов (Jute), нет MVCC, отсутствует HTTP API.

### Кратко

| Задача | Рекомендация |
| :--- | :--- |
| Состояние Kubernetes | etcd |
| Обнаружение сервисов, DNS, mesh | Consul |
| KV с MVCC, watch-информеры, лидер-элекция | etcd |
| Multi-DC каталог сервисов | Consul (peering / WAN) |
| Наследственные JVM-системы (HBase/Solr/Kafka-legacy) | ZooKeeper |

---

## Практические сценарии

### Распределённая блокировка: разные модели

Одна и та же задача — взаимное исключение — решается по-разному, и это влияет на эксплуатацию:

- **etcd:** `clientv3/concurrency` (Mutex на lease + `Compare`) или нативный `Lock` RPC. Блокировка живёт, пока клиент продлевает lease; при разрыве — освобождается. Детали lease — в [Watch и Lease](./watch_lease_internals.md).
- **ZooKeeper:** рецепт на ephemeral-узлах (Curator `InterProcessMutex`): клиент создаёт последовательный ephemeral-узел, минимальный номер владеет блокировкой, остальные следят за предыдущим. Узел исчезает при смерти сессии.
- **Consul:** sessions + KV с `acquire`/`release`; сессия истекает по TTL, ключ освобождается.

Важное общее предупреждение: **владение lease/session не гарантирует владение внешним ресурсом** до истечения TTL — при долгой паузе (GC, подвешивание ВМ) прежний владелец может продолжить работу, хотя блокировка уже перешла другому. Механизм fencing-токена обязателен на стороне ресурса.

### Обнаружение сервисов

- **etcd:** сам по себе не даёт обнаружения. Приложения пишут endpoint'ы как ключи с TTL/lease, читают через watch. Для Kubernetes это берёт на себя `kube-apiserver` + kube-proxy.
- **Consul:** встроено — регистрация агентом, health checks, DNS-ответ только для `passing` инстансов, HTTP API и каталог.
- **ZooKeeper:** сервисы создают ephemeral-узлы; клиент читает список детей и следит за изменениями. Без готового каталога и health checks — это ручная сборка.

### Миграция между системами

Прямой миграции «KV → KV» с сохранением семантики нет из-за различий моделей (MVCC, транзакции, watch). Подход — dual-write/adapter на уровне приложения либо использование shim-слоя (например, Kine для Kubernetes на SQL — см. [etcd: альтернативы и безопасность](../Kubernetes/Concepts/etcd_alternatives_and_security.md)). Перед миграцией фиксируйте требуемые примитивы (транзакции, watch, блокировки) и проверяйте их поддержку целевой системой.

---

## Эксплуатация и наблюдаемость

### Топология, порты и ресурсы

| | etcd | Consul | ZooKeeper |
| :--- | :--- | :--- | :--- |
| Порты по умолчанию | 2379 (клиент), 2380 (peer) | 8500 (HTTP API/UI), 8600 (DNS), 8300/8301/8302 (RPC, serf LAN/WAN) | 2181 (клиент), 2888 (репликация), 3888 (выборы лидера) |
| Размер кластера | 3 или 5, кворум `(N/2)+1` | 3 или 5 (`bootstrap_expect`) | 3 или 5 (ensemble) |
| Стек | Go-процесс; состояние в RAM + WAL и bbolt на диске | Go-процесс; состояние в RAM + Raft WAL и MemDB/FSM | JVM: heap под дерево znodes + транзакционный журнал |
| Требования к диску | p99 `etcd_disk_wal_fsync_duration_seconds` < 10 мс; WAL лучше на выделенном NVMe | Медленный диск растягивает `consul_raft_commitTime` и провоцирует перевыборы | Быстрый диск под журнал; I/O-задержки удлиняют выборы и работу follower'ов |
| Наблюдаемость | `/metrics` на клиентском порту (2379), может выноситься через `--listen-metrics-urls` | `/v1/agent/metrics?format=prometheus` (стандартного пути `/metrics` нет) | `4lw`-команды по 2181, JMX |

Все узлы равноправны: выделенных «мастеров» нет, лидер избирается и может находиться на любом узле, кворум везде считается только по голосующим. Отличия по ролям: у Consul — Autopilot с `voter`/`learner`, у ZooKeeper — observers, у etcd — learners.

### Быстрая диагностика

```bash
# etcd: здоровье, статус, алармы
etcdctl endpoint health
# → HEALTH: http://localhost:2379 is healthy, successful for reason of cluster healthy
etcdctl endpoint status --write-out=table
# → таблица: ENDPOINT, ID, VERSION, DB SIZE, RAFT TERM, RAFT INDEX, LEADER
etcdctl alarm list
# → (пусто — алармов нет; при NOSPACE будет строка memberID/alarm:NOSPACE)

# Consul: кворум и метрики Raft
consul operator raft list-peers
# → для каждого сервера: роль (Voter/Learner), Last Contact (норма < 200 мс), Last Index
curl -s "http://localhost:8500/v1/agent/metrics?format=prometheus" | grep consul_raft_leader
# → consul_raft_leader 1

# ZooKeeper: включите команды (с 3.5.3 по умолчанию разрешена только srvr)
# zoo.cfg: 4lw.commands.whitelist=srvr,mntr,ruok,stat
echo srvr | nc localhost 2181
# → Zookeeper version: 3.9.6-..., Latency min/avg/max: 0/0/0, Mode: leader, Node count: 5
echo mntr | nc localhost 2181
# → zk_server_state leader, zk_avg_latency 0, zk_outstanding_requests 0, zk_znode_count 5
```

Ключевые сигналы для алертинга:

- **etcd:** `etcd_server_has_leader`, `etcd_server_leader_changes_seen_total` (перевыборы), p99 `etcd_disk_wal_fsync_duration_seconds` (норма < 10 мс по официальной FAQ etcd), заполнение квоты `etcd_mvcc_db_total_size_in_bytes / etcd_server_quota_backend_bytes` — алертить задолго до `NOSPACE`. Детали — в [Мониторинге etcd](./etcd_monitoring.md).
- **Consul:** `consul_raft_leader_lastContact` (критично > 200 мс), `consul_raft_commitTime`, `consul_raft_peers` (должно совпадать с ожидаемым числом серверов) — см. [Телеметрия Consul](../Consul/consul_telemetry.md).
- **ZooKeeper:** `zk_server_state`, `zk_avg_latency`, `zk_outstanding_requests`, `zk_num_alive_connections` из `mntr`; для JVM — длительность GC-пауз в логах.

---

## Граничные случаи

- **Линеаризуемость чтений ZooKeeper.** По умолчанию чтение может обслуживаться отставшим follower'ом. Для барьера свежести нужен `sync()` перед чтением; это отличается от линеаризуемых чтений etcd по умолчанию.
- **Размер БД.** Все три системы чувствительны к росту состояния в памяти: KV в etcd и Consul хранится в памяти, ZooKeeper держит дерево в heap. «Максимальный надёжный объём» — это про задержки и память, а не про жёсткий лимит формата.
- **Watcher'ы ZooKeeper — одноразовые.** После срабатывания watcher нужно переустанавливать; пропуск события между переустановками ведёт к рассинхронизации. В etcd watch продолжается с ревизии автоматически.
- **HTTP/JSON API.** У etcd и Consul есть; у ZooKeeper нет (только собственный протокол и сторонние REST-мосты).
- **Multi-DC.** Consul имеет встроенные механизмы (WAN gossip, peering); etcd — нет (требуются внешние решения, обычно отдельный кластер на регион); ZooKeeper — нет.

---

## Типовые отказы и диагностика

| Система | Симптом | Причина | Первые шаги |
| :--- | :--- | :--- | :--- |
| etcd | Аларм `NOSPACE`, ошибка `mvcc: database space exceeded` | БД достигла `quota-backend-bytes` (по умолчанию 2 ГБ) | compaction → `etcdctl defrag --cluster` → `etcdctl alarm disarm`; квоту мониторить заранее (см. [Лимиты](./limits_and_constraints.md)) |
| etcd | `etcdserver: request is too large` | Запрос больше `--max-request-bytes` (1.5 МиБ) | Разбить объект или поднять лимит синхронно на сервере и в клиентском `MaxCallSendMsgSize` |
| etcd | Рост p99 fsync, частые перевыборы | Медленный или общий диск, конкуренты I/O | Вынести WAL на выделенный диск, снять профиль нагрузки |
| Consul | `consul_raft_leader_lastContact > 200 мс`, перевыборы | Диск, CPU, сеть | `consul operator raft list-peers`, метрики Raft ([Телеметрия](../Consul/consul_telemetry.md)) |
| Consul | Сервис пропал из DNS, хотя процесс жив | Health check в `critical`/`warning` — DNS отдаёт только `passing` | `consul members`, `consul health checks`, статус check'а в UI/API |
| ZooKeeper | `mntr`, `ruok`, `stat` не отвечают | 4lw-команды выключены по умолчанию (с 3.5.3) | Добавить `4lw.commands.whitelist` в `zoo.cfg` |
| ZooKeeper | Разрывы сессий при живом процессе | Длинные GC-паузы, медленный диск, слишком короткий session timeout | Логи GC, `zk_avg_latency`, ёмкость heap под дерево znodes |
| Все | Запись недоступна — потеря кворума | Меньшинство живых узлов | Восстановить большинство узлов; размер кластера не уменьшать без расчёта кворума |

Восстановление etcd из снапшота — [Troubleshooting etcd](./troubleshooting.md) и [Maintenance API](./maintenance_api.md); разбор рафт-задержек и катастроф Consul — [Консенсус Raft в Consul](../Consul/consul_consensus.md) и [Disaster Recovery Consul](../Consul/consul-disaster-recovery.md).

---

## Рекомендации по эксплуатации

- **Нечётный размер кластера — 3 или 5.** Кворум `(N/2)+1` переживает потерю одного узла при 3 и двух при 5; чётное число (4) отказоустойчивости не добавляет, но требует 3 узла из 4 для записи.
- **Не совмещайте тяжёлые нагрузки с кластером координации.** Конкуренция за диск — главная причина перевыборов: у etcd и Consul латентность диска входит в путь коммита, у ZooKeeper — в журнал и выборы лидера.
- **Планируйте рост состояния заранее.** Включите автокомпакцию (`--auto-compaction-retention` в etcd), следите за разрывом между `total` и `in_use` и делайте defrag до достижения квоты; у Consul следите за raft-снапшотами (`raft_snapshot_threshold`, по умолчанию 16384 записи); у ZooKeeper держите число znodes и размер данных под контролем.
- **Бэкап проверяйте восстановлением.** `etcdctl snapshot save` / `etcdutl`, `consul snapshot save` дают снимок; регулярное восстановление в тестовый кластер важнее самого факта наличия бэкапа (см. [Проверка бэкапов Consul](../Consul/consul_backup_verification.md)).
- **Fencing-токен на стороне ресурса.** Lease/session подтверждает владение ключом в хранилище, а не внешним ресурсом — без fencing старый владелец после паузы (GC, приостановка ВМ) продолжит писать.
- **Обновления — только с сохранением кворума.** Rolling update по одному узлу, при Kubernetes — PodDisruptionBudget; одновременный вывод большинства узлов равен аварии.

---

## Дополнительная информация

- [etcd versus other key-value stores (официально)](https://etcd.io/docs/v3.6/learning/why) — источник сравнительной таблицы.
- [Обзор Consul](../Consul/consul_overview.md) — архитектура и подсистемы.
- [Консенсус Raft в Consul](../Consul/consul_consensus.md) — WAL, FSM, Autopilot, learners.
- [KV-хранилище Consul](../Consul/consul_kv_store.md) — sessions, CAS, watches.
- [Телеметрия Consul](../Consul/consul_telemetry.md) — эндпоинт метрик и raft-алерты.
- [Apache ZooKeeper Releases](https://zookeeper.apache.org/releases/) — актуальные версии (3.9.x).
- [etcd: альтернативы и безопасность](../Kubernetes/Concepts/etcd_alternatives_and_security.md) — Kine/SQL-бэкенды как замена etcd в Kubernetes.
- [Обнаружение сервисов (обзор)](../Concepts/service-discovery-overview.md) — SD-механизмы всех трёх систем.
- [Распределённые блокировки](../Concepts/Caching/caching_distributed_locks.md) — теория блокировок и fencing.
- [Лимиты и ограничения etcd](./limits_and_constraints.md) — квоты, размеры запросов, пороги.
- [Мониторинг etcd](./etcd_monitoring.md) — метрики, алерты, эндпоинты.
- [Архитектура и концепции etcd](./architecture-and-concepts.md) — устройство самого etcd.
- [Алгоритм Raft](./raft_consensus.md) — теория консенсуса.