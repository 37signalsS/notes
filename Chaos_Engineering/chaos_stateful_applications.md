# Chaos Engineering для Stateful-приложений

## Определения

**Stateful Application Chaos** — направление Chaos Engineering, ориентированное на проверку устойчивости stateful-сервисов: баз данных, очередей, хранилищ конфигурации. В отличие от stateless-подобных экспериментов, здесь критически важна целостность данных и корректность failover.

**Failover** — автоматическое переключение с primary-узла на standby при его отказе. В контексте хаоса проверяется, что переключение происходит без потери данных и деградации сервиса. Для PostgreSQL это Patroni, для MySQL — Orchestrator/Proxy, для Redis — Redis Sentinel/Cluster.

**Consensus Algorithm** — алгоритм достижения согласия в распределенном кластере (Raft, Paxos). Chaos Engineering проверяет, что кластер продолжает функционировать при потере части узлов. Для Raft критично: quorum = (N/2)+1.

**Split-Brain** — состояние, при котором кластер разделяется на две несвязные группы, каждая считающая себя лидером. Для stateful-приложений это критическая ошибка, ведущая к потере данных. Предотвращается через Raft quorum, fencing mechanism (STONITH), lease-based leader election.

**Data Consistency** — согласованность данных между репликами. При инъекции сбоев проверяется, что reads возвращают актуальные данные, а writes не теряются. Используются checksum, row counts, sequence integrity.

**RPO (Recovery Point Objective)** — максимально допустимая потеря данных при сбое. Chaos Engineering проверяет, что фактическая потеря данных не превышает RPO. Для synchronous replication RPO = 0.

**RTO (Recovery Time Objective)** — максимально допустимое время простоя. Chaos Engineering проверяет, что failover завершается за время меньшее RTO. Для Patroni RTO обычно < 60s.

## Основные концепции

### Особенности stateful chaos

Stateful-приложения имеют две критичные зависимости:
1. **Данные** — должны оставаться целостными при любом сбое.
2. **Consensus** — выбор лидера/primary должен быть уникальным.

Поэтому эксперименты для stateful-приложений требуют:
- **Pre-flight checks:** snapshot перед экспериментом, replica status, WAL позиция.
- **Data validation:** checksum таблиц, row counts, sequence integrity после эксперимента.
- **Consistency checks:** `SELECT pg_is_in_recovery()`, `etcdctl endpoint health`, `redis-cli cluster nodes`.

### Классификация stateful-приложений

| Категория | Примеры | Ключевые риски при хаосе |
|:---|:---|:---|
| **Релиational DB** | PostgreSQL, MySQL | Split-brain, data loss, replication lag |
| **NoSQL** | Redis, Cassandra, MongoDB | Quorum loss, stale reads, write timeout |
| **Очереди** | Kafka, RabbitMQ | ISR shrinking, message loss, duplicate delivery |
| **Координация** | etcd, Consul | Raft quorum lost, leader election failure |
| **Хранилище** | Ceph, MinIO | Data corruption, object version conflict |

### Методология experiments for stateful apps

```
1. Pre-flight:
   - Snapshot/backup текущего состояния
   - Зафиксируйте WAL/LSN позицию, replication offset
   - Проверьте health всех реплик

2. Experiment design:
   - Выберите тип сбоя: node failure, network partition, disk latency
   - Определите blast radius: один узел, один диск, subnet
   - Настройте probes: replica health, data consistency, write availability

3. Execution:
   - Инжектируйте сбой
   - Мониторьте: failover time, data loss, consistency
   - Фиксируйте метрики: RTO, RPO, replication lag

4. Validation:
   - Data integrity checksum
   - Read consistency: все реплики возвращают актуальные данные
   - Write path: новые writes доходят до majority
   - No split-brain: только один leader/primary

5. Cleanup:
   - Восстановите узел/сеть
   - Проверьте reintegration в кластер
   - Сравните данные с pre-flight snapshot
```

## Практические сценарии

### Сценарий 1: PostgreSQL streaming replication failover

**Цель:** Проверить, что Patroni выполняет failover за <60s без потери данных.

**Предварительные требования:**

```bash
# Проверка статуса репликации
kubectl exec -n production postgres-primary-0 -- psql -U postgres -c "SELECT * FROM pg_stat_replication;"

# Запись WAL позиции
kubectl exec -n production postgres-primary-0 -- psql -U postgres -c "SELECT pg_current_wal_lsn();"
# → 0/3000028
```

**Инжектируем сбой:** удаляем primary под.

```yaml
apiVersion: chaos-mesh.org/v1alpha1
kind: PodChaos
metadata:
  name: postgres-failover
  namespace: chaos-testing
spec:
  action: pod-kill
  mode: one
  selector:
    namespaces:
      - production
    labelSelectors:
      app: postgres
      role: primary
  gracePeriod: 0
  duration: "5m"
```

**Наблюдаем:**

```bash
# Patroni должен выбрать нового лидера
watch -n 2 'kubectl get pods -n production -l app=postgres'

# Проверка нового primary
kubectl exec -n production postgres-replica-0 -- psql -U postgres -c "SELECT pg_is_in_recovery();"
# → f (новый primary)

# Проверка данных
kubectl exec -n production postgres-replica-0 -- psql -U postgres -c "SELECT count(*) FROM users;"
# → 1500 (совпадает с pre-flight)

# Проверка WAL
kubectl exec -n production postgres-replica-0 -- psql -U postgres -c "SELECT pg_last_wal_replay_lsn();"
# → 0/3000028 или новее (данные не потеряны)
```

**Валидация RPO/RTO:**

```bash
# RTO: время от удаления пода до нового primary
# Должно быть < 60s

# RPO: проверка, что нет незакоммиченных транзакций
# Если replication = synchronous, RPO = 0
# Если asynchronous, проверьте pg_wal на primary (недоступен после kill)
# Альтернатива: проверьте application logs на наличие "connection lost" без потери данных
```

### Сценарий 2: Redis cluster partition

**Цель:** Проверить, что Redis Cluster продолжает работать при потере minority nodes и не возникает split-brain.

**Предварительные требования:**

```bash
# Проверка статуса кластера
redis-cli -h redis-cluster-0 cluster nodes
# → 3 master, 3 replica, все connected

# Запись тестовых данных
redis-cli SET test:chaos "pre-flight" EX 300
redis-cli SET counter:chaos 1000 EX 300
```

**Инжектируем сбой:** сетевой partition между двумя subnets.

```yaml
apiVersion: chaos-mesh.org/v1alpha1
kind: NetworkChaos
metadata:
  name: redis-partition
  namespace: chaos-testing
spec:
  action: partition
  mode: all
  selector:
    namespaces:
      - production
    labelSelectors:
      app: redis
  target:
    mode: all
    selector:
      namespaces:
        - production
      labelSelectors:
        app: redis
  direction: to
  duration: "3m"
```

**Наблюдаем:**

```bash
# Проверка состояния кластера
redis-cli -h redis-cluster-0 cluster nodes
# → Должно быть 2 master доступных (majority из 3)
# → 1 master недоступен (minority partition)

# Запись данных (должна работать через majority)
redis-cli SET test:chaos "during-partition" EX 300
# → OK (majority доступна)

# Чтение данных
redis-cli GET test:chaos
# → "during-partition"

# Нет split-brain: не должно быть двух primary для одного slot
redis-cli -h redis-cluster-0 cluster nodes | grep "master" | wc -l
# → 2 (не 3)
```

**Восстановление и валидация:**

```bash
# Удаление partition
kubectl delete -f redis-partition.yaml

# Проверка reintegration
redis-cli -h redis-cluster-0 cluster nodes
# → Все 3 master вернулись

# Проверка данных: запись во время partition должна сохраниться
redis-cli GET test:chaos
# → "during-partition"

# Проверка счетчика (должен быть consistent)
redis-cli GET counter:chaos
# → 1000 или 1001 (если была запись)
```

### Сценарий 3: Kafka ISR shrinking

**Цель:** Проверить, что Kafka продолжает принимать writes при потере одной реплики и ISR корректно обновляется.

**Предварительные требования:**

```bash
# Проверка ISR
kubectl exec -n production kafka-0 -- kafka-topics.sh --bootstrap-server localhost:9092 --describe --topic orders
# → ISR: 0,1,2 (все реплики в синхронном наборе)

# Запись тестового сообщения
kubectl exec -n production kafka-0 -- kafka-console-producer.sh --broker-list localhost:9092 --topic orders <<< "chaos-test-preflight"
```

**Инжектируем сбой:** убиваем одну реплику.

```yaml
apiVersion: chaos-mesh.org/v1alpha1
kind: PodChaos
metadata:
  name: kafka-replica-kill
  namespace: chaos-testing
spec:
  action: pod-kill
  mode: one
  selector:
    namespaces:
      - production
    labelSelectors:
      app: kafka
  duration: "4m"
```

**Наблюдаем:**

```bash
# Проверка ISR (должно уменьшиться)
kubectl exec -n production kafka-0 -- kafka-topics.sh --bootstrap-server localhost:9092 --describe --topic orders
# → ISR: 0,1 (реплика 2 потеряна)

# Запись сообщений (должна работать)
kubectl exec -n production kafka-0 -- kafka-console-producer.sh --broker-list localhost:9092 --topic orders <<< "chaos-test-during"

# Чтение сообщений (consumer group должен получить все)
kubectl exec -n production kafka-0 -- kafka-console-consumer.sh --bootstrap-server localhost:9092 --topic orders --from-beginning --max-messages 10
# → chaos-test-preflight, chaos-test-during

# Проверка controller election (должен оставаться stable)
kubectl exec -n production kafka-0 -- kafka-metadata-quorum.sh --bootstrap-server localhost:9092 --describe
# → Leader: kafka-0 (не меняется, если убили не controller)
```

**Восстановление:**

```bash
# Удаление эксперимента
kubectl delete -f kafka-replica-kill.yaml

# Проверка reintegration
kubectl exec -n production kafka-0 -- kafka-topics.sh --bootstrap-server localhost:9092 --describe --topic orders
# → ISR: 0,1,2 (все реплики вернулись)

# Проверка offset: consumer group не должен потерять данные
kubectl exec -n production kafka-0 -- kafka-consumer-groups.sh --bootstrap-server localhost:9092 --describe --group order-processors
# → LAG: 0 (все сообщения обработаны)
```

### Сценарий 4: etcd Raft consensus under network partition

**Цель:** Проверить, что etcd продолжает работать при partition, но корректно защищает от split-brain.

**Предварительные требования:**

```bash
# Проверка кластера etcd
ETCDCTL_API=3 etcdctl --endpoints=https://etcd-0:2379 --cacert=/etc/etcd/ssl/ca.crt --cert=/etc/etcd/ssl/etcd.crt --key=/etc/etcd/ssl/etcd.key endpoint health
# → https://etcd-0:2379 is healthy

# Запись тестового ключа
ETCDCTL_API=3 etcdctl --endpoints=https://etcd-0:2379 --cacert=/etc/etcd/ssl/ca.crt --cert=/etc/etcd/ssl/etcd.crt --key=/etc/etcd/ssl/etcd.key put /chaos/test "pre-flight"
```

**Инжектируем сбой:** partition, изолируя один узел.

```yaml
apiVersion: chaos-mesh.org/v1alpha1
kind: NetworkChaos
metadata:
  name: etcd-partition
  namespace: chaos-testing
spec:
  action: partition
  mode: all
  selector:
    namespaces:
      - production
    labelSelectors:
      app: etcd
  target:
    mode: one
    selector:
      namespaces:
        - production
      labelSelectors:
        app: etcd
  direction: both
  duration: "3m"
```

**Наблюдаем:**

```bash
# Проверка лидера (должен оставаться на majority partition)
ETCDCTL_API=3 etcdctl --endpoints=https://etcd-1:2379 --cacert=/etc/etcd/ssl/ca.crt --cert=/etc/etcd/ssl/etcd.crt --key=/etc/etcd/ssl/etcd.key endpoint status
# → leader: etcd-1 (majority partition)

# Запись данных (должна работать через majority)
ETCDCTL_API=3 etcdctl --endpoints=https://etcd-1:2379 --cacert=/etc/etcd/ssl/ca.crt --cert=/etc/etcd/ssl/etcd.crt --key=/etc/etcd/ssl/etcd.key put /chaos/test "during-partition"
# → OK

# Изолированный узел не должен быть лидером
ETCDCTL_API=3 etcdctl --endpoints=https://etcd-2:2379 --cacert=/etc/etcd/ssl/ca.crt --cert=/etc/etcd/ssl/etcd.crt --key=/etc/etcd/ssl/etcd.key endpoint status
# → leader: none (или error) — изолированный узел не может быть лидером

# Нет split-brain: запись на изолированный узел должна отклоняться
ETCDCTL_API=3 etcdctl --endpoints=https://etcd-2:2379 --cacert=/etc/etcd/ssl/ca.crt --cert=/etc/etcd/ssl/etcd.crt --key=/etc/etcd/ssl/etcd.key put /chaos/test "split-brain-attempt"
# → Error: etcdserver: request timed out
```

**Восстановление:**

```bash
# Удаление partition
kubectl delete -f etcd-partition.yaml

# Проверка reintegration
ETCDCTL_API=3 etcdctl --endpoints=https://etcd-0:2379,https://etcd-1:2379,https://etcd-2:2379 --cacert=/etc/etcd/ssl/ca.crt --cert=/etc/etcd/ssl/etcd.crt --key=/etc/etcd/ssl/etcd.key endpoint health
# → Все endpoints healthy

# Проверка данных
ETCDCTL_API=3 etcdctl --endpoints=https://etcd-0:2379 --cacert=/etc/etcd/ssl/ca.crt --cert=/etc/etcd/ssl/etcd.crt --key=/etc/etcd/ssl/etcd.key get /chaos/test
# → "during-partition" (данные сохранились)
```

### Сценарий 5: MySQL semi-sync replication under latency

**Цель:** Проверить, что semi-sync replication блокирует writes при потере sync replica.

**Инструмент:** Chaos Mesh + MySQL audit.

**Шаги:**

1. **Настройте semi-sync:** `rpl_semi_sync_master_timeout=10s`, `rpl_semi_sync_master_wait_point=AFTER_SYNC`.
2. **Инжектируйте задержку:** 5s задержка на sync replica.
3. **Наблюдайте:**
   - Primary блокирует writes после 10s timeout.
   - Приложение получает timeout, а не silent data loss.
   - Async replica продолжает репликацию.

**Манифест:**

```yaml
apiVersion: chaos-mesh.org/v1alpha1
kind: NetworkChaos
metadata:
  name: mysql-semi-sync-test
spec:
  action: delay
  mode: one
  selector:
    labelSelectors:
      app: mysql
      role: replica
  delay:
    latency: "5s"
  duration: "2m"
```

### Сценарий 6: Cassandra multi-DC consistency

**Цель:** Проверить, что Cassandra продолжает обслуживать reads при отказе одного DC, если consistency level = LOCAL_QUORUM.

**Инструмент:** Chaos Mesh + Cassandra nodetool.

**Шаги:**

1. **Настройте consistency:** `LOCAL_QUORUM` для reads/writes.
2. **Инжектируем сбой:** network partition для одного DC.
3. **Наблюдаем:**
   - Reads/writes в оставшемся DC работают.
   - Нет unavailable exception.
   - Данные consistent в пределах доступного DC.

## Операции и команды

### PostgreSQL

```bash
# Проверка репликации
kubectl exec -n production postgres-primary-0 -- psql -U postgres -c "SELECT * FROM pg_stat_replication;"

# Проверка lag
kubectl exec -n production postgres-replica-0 -- psql -U postgres -c "SELECT pg_last_wal_replay_lsn() - pg_current_wal_lsn() AS lag_bytes;"

# Ручой failover (Patroni)
kubectl exec -n production postgres-replica-0 -- patronictl failover postgres-cluster
```

### Redis

```bash
# Проверка кластера
redis-cli -h redis-cluster-0 cluster nodes

# Проверка quorum
redis-cli -h redis-cluster-0 cluster info | grep cluster_state
# → cluster_state:ok

# Валидация данных
redis-cli -h redis-cluster-0 debug digest
# → хэш всех данных (сравнить до и после эксперимента)
```

### Kafka

```bash
# Проверка ISR
kubectl exec -n production kafka-0 -- kafka-topics.sh --bootstrap-server localhost:9092 --describe --topic orders

# Проверка controller
kubectl exec -n production kafka-0 -- kafka-metadata-quorum.sh --bootstrap-server localhost:9092 --describe

# Consumer group lag
kubectl exec -n production kafka-0 -- kafka-consumer-groups.sh --bootstrap-server localhost:9092 --describe --group order-processors
```

### etcd

```bash
# Проверка здоровья
ETCDCTL_API=3 etcdctl --endpoints=https://etcd-0:2379,https://etcd-1:2379,https://etcd-2:2379 endpoint health

# Проверка лидера
ETCDCTL_API=3 etcdctl --endpoints=https://etcd-0:2379,https://etcd-1:2379,https://etcd-2:2379 endpoint status

# Compact/defrag
ETCDCTL_API=3 etcdctl --endpoints=https://etcd-0:2379 compact 1000
ETCDCTL_API=3 etcdctl --endpoints=https://etcd-0:2379 defrag
```

### MySQL

```bash
# Проверка репликации
kubectl exec -n production mysql-primary-0 -- mysql -u root -p -e "SHOW SLAVE STATUS\G"

# Проверка GTID
kubectl exec -n production mysql-primary-0 -- mysql -u root -p -e "SHOW MASTER STATUS;"

# Ручой failover
kubectl exec -n production mysql-replica-0 -- mysql -u root -p -e "STOP SLAVE; RESET SLAVE ALL;"
```

## Устранение неполадок

| Проблема | Вероятная причина | Решение |
|:---|:---|:---|
| **Split-brain при failover** | Два узла считают себя primary | Проверьте `fencing mechanism`: STONITH, quorum, lease. Настройте `patronictl` fence. |
| **Data loss после failover** | Async replication, RPO > 0 | Перейдите на synchronous replication или semi-sync. Увеличьте `commit_delay`. |
| **Replication lag растет** | Сетевая задержка или дисковая нагрузка | Проверьте `pg_stat_replication`, `netstat`, `iostat`. Увеличьте `wal_sender_timeout`. |
| **etcd lost quorum** | Больше половины узлов недоступно | Восстановите кластер из snapshot. Для 3-узлового кластера допустима потеря 1 узла. |
| **Redis cluster enters fail state** | Minority partition имеет majority hash slots | Используйте `cluster-require-full-coverage=no` только для отладки. В production — восстановите cluster. |
| **Kafka ISR не восстанавливается** | Replica не может догнать ISR | Проверьте `replica.fetch.wait.max.ms`, `num.replica.fetchers`. Увеличьте `replica.fetch.max.bytes`. |
| **Cassandra hinted handoff не работает** | Диск полон или hints TTL истек | Проверьте `hints_directory`, `max_hints_delivery_threads`. Очистите старые hints. |
| **MySQL semi-sync timeout** | Replica недоступна дольше `rpl_semi_sync_master_timeout` | Увеличьте timeout или добавьте еще одну sync replica. |

## Лучшие практики

### Безопасность

1. **Всегда делайте snapshot перед экспериментом** — для PostgreSQL: `pg_basebackup`, для Redis: `BGSAVE`, для etcd: `etcdctl snapshot save`.
2. **Тестируйте в staging с production-данными** — обезличьте данные, но сохраните объем и схему.
3. **Начинайте с одного узла** — никогда не применяйте partition ко всему кластеру сразу.
4. **Имейте emergency stop** — автоматическая остановка при data loss detection.
5. **Восстанавливайте данные после эксперимента** — сравните checksum с pre-flight snapshot.

### Мониторинг

6. **Следите за replication lag** — Prometheus gauge `pg_replication_lag_seconds`, `kafka_controller_kafkacontroller_replication_manager_under_replicated_partitions`.
7. **Настройте алерты на data loss** — `pg_wal` growth anomaly, `kafka_under_replicated_partitions > 0`.
8. **Используйте distributed traces** — Jaeger trace должен показывать, на каком шаге произошел failover.
9. **Ведите timeline эксперимента** — время удаления узла, время failover, время reintegration.

### Валидация

10. **Проверяйте data consistency** — row counts, checksums, sequence values после эксперимента.
11. **Тестируйте write path** — убедитесь, что новые writes доходят до majority.
12. **Тестируйте read consistency** — все reads должны возвращать актуальные данные, не stale.
13. **Тестируйте recovery** — восстановленный узел должен синхронизировать данные без ручного вмешательства.

## Дополнительная информация

### Связанные технологии

- **Patroni** — HA для PostgreSQL: автоматический failover, consensus через etcd/Consul.
- **Redis Cluster** — распределенный Redis с sharding и replication.
- **Kafka KRaft** — Kafka без ZooKeeper, метаданные в raft-логе.
- **etcd** — распределенный ключ-зна store на основе Raft.

### См. также

- [Chaos Engineering — практическое руководство](chaos_engineering_practical.md) — Game Days, где stateful chaos тестируется в комплексе.
- [Chaos Engineering — метрики](chaos_engineering_metrics.md) — SLI/SLO для баз данных.
- [Chaos Engineering — инструменты](chaos_engineering_tools.md) — Chaos Mesh, Litmus для stateful workloads.
