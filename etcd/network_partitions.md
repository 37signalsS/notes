# Сетевые разделения и Gray Failure в etcd

**Сетевые разделения (Network Partitions)** и **Gray Failures** — это самые опасные failure modes для распределённых систем. etcd спроектирован для их обработки, но понимание того, что происходит "под капотом", критично для production.

## Определения

| Термин | Описание |
| :--- | :--- |
| **Network Partition** | Разрыв сетевой связности между частями кластера. Часть узлов теряет связь с большинством. |
| **Split-Brain** | Ситуация, когда обе части partition считают, что они имеют кворум (в etcd невозможно благодаря Raft). |
| **Gray Failure** | Узел частично работает: принимает запросы, но не отвечает на heartbeats или отвечает с задержкой. |
| **Minority** | Часть кластера, не имеющая кворума. Блокирует записи, ищет лидера. |
| **Majority** | Часть кластера с кворумом. Продолжает работу. |
| **CheckQuorum** | Механизм, при котором лидер добровольно слагает полномочия, если потерял связь с большинством. |
| **Pre-Vote** | Предварительное голосование без увеличения Term (предотвращает дребезг лидера). |

---

## Основные концепции

### Что происходит при Network Partition

Рассмотрим кластер из 3 узлов (A, B, C), лидер = A.

**Сценарий 1: Лидер изолирован (A ↔ {B, C} разрыв)**

1. A перестаёт получать heartbeats от B и C.
2. A переходит в состояние Follower, запускает выборы.
3. B и C имеют кворум (2 из 3). B или C становится новым лидером.
4. **Результат:** A → read-only, B+C → read-write.

**Сценарий 2: Follower изолирован (B ↔ {A, C} разрыв)**

1. B перестаёт получать heartbeats от A.
2. B переходит в Candidate, запускает выборы.
3. A и C имеют кворум. A остаётся лидером.
4. **Результат:** B → read-only, A+C → read-write.

**Сценарий 3: 2-2 partition (кластер из 4 узлов)**

1. Разрыв на {A, B} и {C, D}.
2. Ни одна часть не имеет кворума (нужно 3 из 4).
3. **Результат:** ВСЕ узлы блокированы для записи.
4. Это одна из причин, почему чётное количество узлов — антипаттерн.

### Почему классический Split-Brain невозможен

Raft гарантирует, что в один Term может быть только один лидер:

1. Лидер обязан получить голоса от большинства (кворума).
2. При partition только одна часть имеет кворум.
3. Вторая часть не может избрать лидера (не набирает кворум).
4. Следовательно, два лидера в один Term — невозможны.

**Но:** Если partition разрешается, старый лидер (если он думал, что он ещё лидер) сложит полномочия при получении нового Term от нового лидера.

### Gray Failure: самый опасный сценарий

Gray Failure — это когда узел:
- Принимает запросы от клиентов (TCP соединение живо).
- Не отвечает на Raft heartbeats (или отвечает с задержкой > election-timeout).

**Что происходит:**
1. Лидер считает, что follower отвалился, исключает его из кворума.
2. Если лидер потерял кворум — он слагает полномочия (CheckQuorum).
3. Если лидер всё ещё имеет кворум — запись продолжается, но latency растёт (ожидание оставшихся follower'ов).
4. Если "серый" узел внезапно оживает — он может иметь устаревший Term и вызвать лишние выборы.

**Диагностика:**
```bash
# Метрика: heartbeat send failures
curl -s http://localhost:2379/metrics | grep etcd_server_heartbeat_send_failures_total

# Метрика: proposal failed
curl -s http://localhost:2379/metrics | grep etcd_server_proposals_failed_total

# Проверка RTT
curl -s http://localhost:2379/metrics | grep etcd_network_peer_round_trip_time_seconds
```

### CheckQuorum (v3.4+)

Лидер периодически проверяет, получает ли он ответы от большинства узлов. Включён по умолчанию в etcd 3.4+ во всех режимах запуска (`CheckQuorum: true` в `startNode`/`restartNode`/`restartAsStandaloneNode`, `etcdserver/raft.go`, тег v3.4.13); CLI-флага `--check-quorum` в etcd нет (настройка raft-уровневая, не пользовательская).

**Если CheckQuorum отключён (только в кастомных встраиваниях raft с `CheckQuorum: false`):**
- Лидер может оставаться в меньшинстве, "притворяясь", что он лидер.
- Клиенты, подключённые к нему, получают `Unavailable` или `DeadlineExceeded`.
- Включённый CheckQuorum предотвращает "зависание" запросов на изолированном лидере.

### Pre-Vote (v3.5+)

Перед началом полноценных выборов узел отправляет `MsgPreVote` без увеличения Term:

1. Узел переходит в **Pre-Candidate**.
2. Рассылает `RequestVote` (Pre-Vote) всем узлам.
3. Другие узлы отвечают "да", только если они тоже не слышали лидера.
4. Если кворум не набран — Term не увеличивается, выборы отменяются.

**Benefit:** Предотвращает "дребезг" лидера при кратковременных сетевых миганиях.

---

## Практические сценарии

### Имитация partition (Chaos Engineering)

```bash
# Используйте iptables для имитации потери пакетов между узлами
iptables -A OUTPUT -p tcp --dport 2380 -d 10.0.1.11 -j DROP

# Наблюдать за кластером
watch -n 1 'etcdctl endpoint status --cluster -w table | grep -E "LEADER|HEALTH"'

# Восстановить
iptables -D OUTPUT -p tcp --dport 2380 -d 10.0.1.11 -j DROP
```

**Или через Chaos Mesh:**
```yaml
apiVersion: chaos-mesh.org/v1alpha1
kind: NetworkChaos
metadata:
  name: etcd-partition
spec:
  selector:
    namespaces:
      - kube-system
    labelSelectors:
      component: etcd
  mode: one
  action: partition
  direction: both
  target:
    selector:
      namespaces:
        - kube-system
    mode: all
  delay:
    percentage: 100
    correlation: 0
    jitter: 0ms
```

### Проверка устойчивости к partition

```bash
# 1. Baseline: записать количество leader changes
curl -s http://localhost:2379/metrics | grep etcd_server_leader_changes_seen_total

# 2. Имитировать partition (через iptables или Chaos Mesh)

# 3. Наблюдать: лидер должен переизбраться 1 раз (если лидер изолирован)
# → Ожидаемо: leader_changes + 1

# 4. Восстановить partition

# 5. Проверить, что leader_changes вернулся к baseline
```

### Автоматическое восстановление после partition

etcd **автоматически** восстанавливается после разрешения partition:

1. Изолированные узлы обнаруживают новый Term (более высокий).
2. Они добровольно присоединяются к новому лидеру.
3. Отставшие узлы получают snapshot или инкрементальный WAL.
4. Данные синхронизируются.

**Не требуется ручное вмешательство** — если partition разрешилась и кворум жив.

---

## Troubleshooting

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| Лидер flapping (leader_changes > 5/мин) | Частые partition или высокий RTT | Увеличить `election-timeout`; проверить сеть; включить Pre-Vote |
| `no leader` на всех узлах | Потеря кворума (>50% узлов недоступны) | Восстановить доступ к большинству; восстановить из снапшота |
| `etcdserver: request timed out` | Клиент подключён к изолированному лидеру | Проверить `etcdctl endpoint status`; использовать LB для распределения клиентов |
| Gray failure (высокий RTT, но пинги проходят) | Пакеты теряются или задерживаются на уровне TCP | Проверить `tcpdump` на порту 2380; проверить switch/bufferbloat |
| Follower не может синхронизироваться после partition | Разрыв слишком долгий, WAL устарел | Лидер отправит snapshot; проверить `etcdctl endpoint status` |

---

## Best Practices

- **Чётное число узлов — антипаттерн:** При 2-2 partition кластер полностью блокируется.
- **Multi-zone:** Размещайте узлы в разных зонах отказа, но убедитесь, что RTT < 50 ms.
- **Heartbeat interval > RTT:** Если RTT между зонами = 30 ms, `heartbeat-interval` должен быть ≥ 100 ms.
- **Election timeout ≥ 10× heartbeat:** Предотвращает ложные выборы при джиттере.
- **Мониторинг leader changes:** `rate(etcd_server_leader_changes_seen_total[15m]) > 3` — алерт.
- **Chaos Engineering:** Регулярно тестируйте partition resilience в staging.

---

## Edge Cases

- **Сетевой partition длительностью > election-timeout:** Если partition длится долго, лидер успеет сложить полномочия. При восстановлении partition новый лидер уже будет выбран.
- **Два лидера на короткое время:** При очень быстром разрешении partition возможна ситуация, когда старый лидер ещё не знает о новом. Но Raft гарантирует, что старый лидер не примет никаких решений (нет кворума).
- **Learner во время partition:** Learner не участвует в кворуме. Если partition изолирует learner, это не влияет на работоспособность кластера.
- **Cluster Fencing при DR:** При полной потере кворума и восстановлении из снапшота используйте `--initial-cluster-token` для предотвращения "слияния" старого и нового кластера.

---

## См. также

* **[Raft консенсус](./raft_consensus.md)** — детали алгоритма и выборов.
* **[Кластеризация и восстановление](./clustering_and_recovery.md)** — multi-zone и HA-топологии.
* **[Систематический troubleshooting](./troubleshooting.md)** — playbook для partition.
