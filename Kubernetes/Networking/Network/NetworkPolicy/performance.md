# NetworkPolicy: Производительность и масштабирование

## Определения

**Throughput (Пропускная способность)** — объем сетевого трафика, обрабатываемого data plane в единицу времени (обычно в Gbps или Mpps — миллионах пакетов в секунду). NetworkPolicy добавляет overhead на обработку каждого пакета, который зависит от количества политик, их сложности и используемого механизма фильтрации.

**Latency (Задержка)** — время обработки одного пакета от момента поступления в network stack до принятия решения о разрешении/блокировке. Измеряется в микросекундах (μs). Для production-сред критичен tail latency (P99).

**Policy Lookup Time (Время поиска правила)** — время, необходимое data plane для проверки пакета против всех применяемых политик. Определяется алгоритмом поиска: O(N) для iptables (линейный перебор), O(1) для eBPF (хеш-таблицы).

**Data Plane** — механизм обработки пакетов в ядре Linux. Типичные реализации: iptables (цепочки правил), nftables (дерево правил), eBPF (программы в kernel), OVS (Open vSwitch).

**conntrack (Connection Tracking)** — механизм ядра Linux, отслеживающий состояния активных соединений. NetworkPolicy использует conntrack для stateful фильтрации. Размер таблицы conntrack (`nf_conntrack_max`) напрямую влияет на производительность.

**Identity-based Policy (Политика на основе идентичности)** — подход, при котором пакеты идентифицируются не по IP-адресу, а по метке пода/service account (Cilium, Calico eBPF). Позволяет эффективнее обрабатывать политики, так как идентичность стабильнее IP.

**O(N) vs O(1)** — классификация алгоритмов поиска: O(N) означает линейный рост времени с увеличением количества правил (iptables), O(1) — константное время (eBPF hash tables).

## Базовые Концепции

### Факторы, влияющие на производительность NetworkPolicy

| Фактор | Влияние | Масштаб проблемы |
| :--- | :--- | :--- |
| **Количество политик** | Линейный рост времени проверки в iptables/nftables | >1000 политик — заметное снижение |
| **Количество правил в политике** | Каждое правило — дополнительная проверка | >50 правил в одной политике |
| **Количество подов на узле** | Каждый под = набор правил в data plane | >200 подов на узле |
| **Тип data plane** | iptables O(N), eBPF O(1) | Критичен при масштабе |
| **Сложность селекторов** | matchExpressions дороже matchLabels | Избегайте сложных выражений |
| **conntrack table size** | При переполнении — packet drop | nf_conntrack_max слишком мал |

### Сравнение data plane по производительности

| Data Plane | Алгоритм поиска | Overhead на пакет | Пригодность для >1000 политик |
| :--- | :--- | :--- | :--- |
| **iptables** | O(N) — линейный перебор | Средний | Плохая |
| **nftables** | O(log N) — дерево правил | Низкий | Средняя |
| **eBPF** | O(1) — хеш-таблица | Минимальный | Отличная |
| **OVS (Antrea)** | O(1) — flow tables | Низкий | Хорошая |

> **Кросс-ссылка:** Подробное сравнение CNI — [Реализация NetworkPolicy в CNI](./cni_implementation.md)

### Как iptables обрабатывает NetworkPolicy

При использовании Calico/Flannel в режиме iptables:

```
Пакет → PREROUTING → FORWARD → Conntrack Check → Chain Matching → ALLOW/DROP
                                  │
                                  ├── Calico chains (cali-*)
                                  │   ├── cali-fw (forward)
                                  │   ├── cali-po (post-routing)
                                  │   └── cali-pi (pre-ingress)
                                  │
                                  └── Проверка каждого правила последовательно
                                      при большом количестве правил = O(N)
```

Каждая NetworkPolicy генерирует набор iptables-цепочек. При 500 политик на узле может быть 10,000+ правил iptables. Ядро Linux проверяет каждое правило последовательно для каждого пакета.

### Как eBPF обрабатывает NetworkPolicy

eBPF заменяет цепочки iptables хеш-таблицами:

```
Пакет → eBPF Program (XDP/TC) → Hash Table Lookup → ALLOW/DROP
            │
            ├── Identity Map (pod identity → policy set)
            ├── Policy Map (policy ID → rules)
            └── Verdict Map (connection → verdict cache)
```

- **Hash Table Lookup** — O(1): проверка наличия правила за константное время
- **Verdict Cache** — повторные пакеты одного соединения обрабатываются мгновенно
- **Per-CPU Maps** — нет блокировок между CPU

### Пороговые значения для production

| Метрика | Рекомендация | Действие при превышении |
| :--- | :--- | :--- |
| **Количество политик на кластер** | <10000 | Оптимизируйте: объединяйте похожие правила |
| **Количество политик на узел** | <500 | Включите Typha (Calico) или eBPF |
| **Количество правил на под** | <20 | Упрощайте селекторы, группируйте порты |
| **conntrack table size** | >256K | Увеличьте `nf_conntrack_max` |
| **Felix execution time** | <10ms | Мониторьте через Prometheus |
| **eBPF map pressure** | <80% | Расширяйте BPF maps |

### Мониторинг производительности

**Calico Felix Metrics (Prometheus):**

```bash
# Включение метрик
calicoctl patch felixconfiguration default --patch '{"spec": {"prometheusMetricsEnabled": true}}'

# Ключевые метрики
curl http://localhost:9091/metrics | grep felix

# felix_execution_time_seconds — время применения политик
# felix_active_local_endpoints — количество активных подов
# felix_cluster_num_policies — общее количество политик
# felix_cluster_num_hosts — количество узлов в кластере
# felix_go_goroutines — количество горутин Felix
```

**conntrack monitoring:**

```bash
# Проверка размера таблицы
sysctl net.netfilter.nf_conntrack_max
# → net.netfilter.nf_conntrack_max = 262144

# Проверка текущего использования
cat /proc/sys/net/netfilter/nf_conntrack_count
# → 15234

# Статистика dropping
conntrack -S
# → cpu=0 found=12345 inserted=12340 dropped=0 invalid=12
```

## Практические сценарии

### Сценарий 1: Бенчмаркирование iptables vs eBPF

Сравнение производительности при большом количестве политик:

```bash
# 1. Создайте тестовый namespace с 100 подами
kubectl create namespace bench-test
for i in $(seq 1 100); do
  kubectl run pod-$i --image=busybox --restart=Never -n bench-test -- sleep 3600
done

# 2. Создайте 500 NetworkPolicy (каждая для своего пода)
for i in $(seq 1 500); do
  cat <<EOF | kubectl apply -f -
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: bench-pol-$i
  namespace: bench-test
spec:
  podSelector:
    matchLabels:
      run: pod-$((i % 100 + 1))
  policyTypes:
  - Ingress
  - Egress
  ingress:
  - from:
    - podSelector:
        matchLabels:
          run: pod-$(((i + 1) % 100 + 1))
  egress:
  - ports:
    - protocol: TCP
      port: 8080
EOF
done

# 3. Измерьте latency между подами (baseline)
kubectl exec -n bench-test pod-1 -- ping -c 100 pod-2.bench-test.svc.cluster.local
# → rtt min/avg/max/mdev = 0.100/0.150/0.200/0.020 ms

# 4. Проверьте время применения Felix (Calico)
calicoctl get felixconfiguration default -o yaml | grep executionTime
```

### Сценарий 2: Оптимизация при большом количестве политик

Стратегии снижения нагрузки:

```yaml
# ПЛОХО: 100 отдельных политик по одному правилу каждая
---
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-app-1
spec:
  podSelector:
    matchLabels: {app: app-1}
  ingress:
  - from: [{podSelector: {matchLabels: {app: frontend}}}]
    ports: [{port: 8080}]
---
# ... (еще 99 таких же)

# ХОРОШО: Одна политика с grouped правилами
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-frontend-to-backends
spec:
  podSelector:
    matchLabels:
      tier: backend
  ingress:
  - from:
    - podSelector:
        matchLabels:
          app: frontend
    ports:
    - protocol: TCP
      port: 8080
    - protocol: TCP
      port: 8443
```

**Правила оптимизации:**
1. **Группируйте поды по меткам:** Вместо 100 политик для 100 подов — 1 политика с `matchLabels: {tier: backend}`
2. **Используйте namespaceSelector:** Для межсервисных политик ограничивайте scope namespace
3. **Избегайте endPort:** Диапазоны портов генерируют больше правил в iptables
4. **Упрощайте селекторы:** `matchLabels` быстрее `matchExpressions`

### Сценарий 3: Настройка conntrack для высоконагруженных сред

```bash
# Увеличение размера таблицы conntrack
echo "net.netfilter.nf_conntrack_max=1048576" >> /etc/sysctl.d/99-conntrack.conf
echo "net.netfilter.nf_conntrack_buckets=262144" >> /etc/sysctl.d/99-conntrack.conf

# Снижение тайм-аутов для быстрой очистки
echo "net.netfilter.nf_conntrack_tcp_timeout_established=3600" >> /etc/sysctl.d/99-conntrack.conf
echo "net.netfilter.nf_conntrack_tcp_timeout_time_wait=30" >> /etc/sysctl.d/99-conntrack.conf
echo "net.netfilter.nf_conntrack_udp_timeout=30" >> /etc/sysctl.d/99-conntrack.conf
echo "net.netfilter.nf_conntrack_udp_timeout_stream=60" >> /etc/sysctl.d/99-conntrack.conf

sysctl --system

# Проверка
sysctl net.netfilter.nf_conntrack_max
# → 1048576
```

> **Важно:** Увеличение `nf_conntrack_max` требует пропорционального увеличения памяти. Каждая запись conntrack ~300 байт. Для 1M записей: ~300 МБ RAM.

### Сценарий 4: Миграция iptables → eBPF для производительности

```bash
# 1. Проверка версии ядра
uname -r
# → Требуется 5.3+ для eBPF, 5.10+ для nftables

# 2. Проверка смонтированной BPF filesystem
mount | grep bpf
# → bpf on /sys/fs/bpf type bpf (rw,nosuid,nodev,noexec,relatime)

# 3. Включение eBPF dataplane (Calico)
calicoctl patch felixconfiguration default --patch '{"spec": {"bpfEnabled": true, "bpfKubeProxyIptablesCleanupEnabled": true}}'

# 4. Проверка замены kube-proxy
kubectl get pods -n kube-system -l k8s-app=kube-proxy
# → Не должно быть подов kube-proxy

# 5. Верификация
kubectl exec -n calico-system <calico-node-pod> -- calico-node -bpf counters dump
# → Active Sims: 5
# → Packets passed: 123456
```

### Сценарий 5: Мониторинг через Prometheus + Grafana

```yaml
# ServiceMonitor для Felix (если используется Prometheus Operator)
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: felix-metrics
  namespace: monitoring
spec:
  selector:
    matchLabels:
      k8s-app: calico-node
  namespaceSelector:
    matchNames:
    - calico-system
  endpoints:
  - port: metrics
    interval: 30s
---
# Grafana Dashboard ID: 16658 (Calico Felix)
# Ключевые панели:
# - Felix Execution Time (P50, P95, P99)
# - Active Endpoints per Node
# - Number of Policies
# - WireGuard Throughput
```

## Дополнительная информация

### Чек-лист оптимизации производительности

| # | Действие | Приоритет |
| :--- | :--- | :--- |
| 1 | Перейти на eBPF dataplane (ядро 5.3+) | Высокий |
| 2 | Группировать поды по меткам вместо individual policies | Высокий |
| 3 | Увеличить `nf_conntrack_max` до 512K-1M | Средний |
| 4 | Включить Typha для кластеров >50 узлов (Calico) | Средний |
| 5 | Ограничить количество правил в одной политике (<50) | Средний |
| 6 | Использовать `matchLabels` вместо `matchExpressions` | Низкий |
| 7 | Настроить мониторинг Felix/Cilium metrics | Высокий |
| 8 | Регулярно проверять `conntrack -S` на drops | Средний |

### Бенчмарки (ориентировочные)

| Сценарий | iptables | eBPF | Улучшение |
| :--- | :--- | :--- | :--- |
| **500 политик, latency P50** | ~150 μs | ~12 μs | 12x |
| **500 политик, latency P99** | ~800 μs | ~25 μs | 32x |
| **1000 политик, throughput** | ~800K pps | ~3.5M pps | 4.4x |
| **conntrack满, packet drop** | 100% new connections | 100% new connections | Одинаково |
| **Обновление политики** | ~50ms (iptables-restore) | ~1ms (BPF map update) | 50x |

> **Примечание:** Бенчмарки зависят от hardware, kernel version, и конкретной конфигурации. Приведенные числа — ориентировочные значения из production-сред.

### Связанные темы

* [Реализация NetworkPolicy в CNI](./cni_implementation.md) — сравнение CNI по поддержке
* [eBPF в Kubernetes](../../Networking/Network/CNI/ebpf.md) — архитектура eBPF
* [conntrack и NetworkPolicy](./rule_logic.md) — stateful фильтрация
* [Лучшие практики](./best_practices.md) — рекомендации по оптимизации
