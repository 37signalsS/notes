# Оптимизация сетевой производительности в Kubernetes

## Определения

**Network Performance Tuning** — процесс оптимизации сетевого стека Kubernetes для максимальной производительности, минимальных задержек и эффективного использования ресурсов.

**conntrack Tuning** — оптимизация параметров таблицы отслеживания соединений ядра Linux для предотвращения переполнения и снижения задержек.

**MTU Optimization** — настройка Maximum Transmission Unit для минимизации фрагментации и максимальной пропускной способности.

**TCP Buffer Tuning** — оптимизация размеров буферов TCP-сокетов для улучшения производительности на высокоскоростных линиях.

**XDP (eXpress Data Path)** — обработка пакетов на уровне драйвера сетевой карты, до поступления в сетевой стек ядра.

**Bandwidth Manager** — компонент Cilium для управления полосой пропускания и предотвращения эффекта шумного соседа через EDT (Earliest Departure Time).

---

## Основные концепции

### Уровни оптимизации

```
1. Уровень ядра Linux
   ├─ conntrack (размер, таймауты)
   ├─ TCP buffers (rmem/wmem)
   ├─ net.core.somaxconn
   └─ net.ipv4.tcp_max_syn_backlog

2. Уровень CNI
   ├─ MTU (1500 -> 1450 для VXLAN)
   ├─ Routing mode (overlay vs native)
   └─ eBPF acceleration

3. Уровень kube-proxy
   ├─ Режим (iptables -> IPVS -> eBPF)
   ├─ minSyncPeriod
   └─ Session Affinity

4. Уровень приложения
   ├─ Connection pooling
   ├─ Keep-alive settings
   └─ Graceful termination
```

### Ключевые метрики

| Метрика | Описание | Целевое значение |
| :--- | :--- | :--- |
| **Latency (p99)** | Задержка 99% запросов | < 1ms внутрикластерных |
| **Throughput** | Пропускная способность | > 10 Gbps для standard NIC |
| **Packet Loss** | Потеря пакетов | < 0.1% |
| **CPU Usage** | Нагрузка на CPU от сети | < 30% на узле |
| **conntrack Usage** | Использование таблицы conntrack | < 80% от max |

---

## Практические сценарии

### 1. Оптимизация conntrack

```bash
# Текущее использование
sudo sysctl net.netfilter.nf_conntrack_count
sudo sysctl net.netfilter.nf_conntrack_max

# Статистика ошибок
sudo conntrack -S
```

```bash
# /etc/sysctl.d/99-kubernetes-conntrack.conf
net.netfilter.nf_conntrack_max = 1048576
net.netfilter.nf_conntrack_buckets = 262144
net.netfilter.nf_conntrack_tcp_timeout_established = 7200
net.netfilter.nf_conntrack_tcp_timeout_time_wait = 30
net.netfilter.nf_conntrack_tcp_timeout_close_wait = 15
net.netfilter.nf_conntrack_tcp_timeout_fin_wait = 15
net.netfilter.nf_conntrack_udp_timeout = 30
net.netfilter.nf_conntrack_udp_timeout_stream = 60

sudo sysctl -p /etc/sysctl.d/99-kubernetes-conntrack.conf
```

**Рекомендации:**
- Кластеры <1000 подов: `nf_conntrack_max = 524288`
- Кластеры 1000-5000 подов: `nf_conntrack_max = 1048576`
- Кластеры >5000 подов: `nf_conntrack_max = 2097152`

### 2. Оптимизация TCP-буферов

```bash
# /etc/sysctl.d/99-kubernetes-tcp.conf
net.core.rmem_max = 16777216
net.core.wmem_max = 16777216
net.core.rmem_default = 1048576
net.core.wmem_default = 1048576
net.ipv4.tcp_rmem = 4096 1048576 16777216
net.ipv4.tcp_wmem = 4096 1048576 16777216
net.core.somaxconn = 65535
net.ipv4.tcp_max_syn_backlog = 65535
net.ipv4.tcp_fin_timeout = 15
net.ipv4.tcp_tw_reuse = 1
net.ipv4.tcp_keepalive_time = 600
net.ipv4.tcp_keepalive_intvl = 30
net.ipv4.tcp_keepalive_probes = 5

sudo sysctl -p /etc/sysctl.d/99-kubernetes-tcp.conf
```

### 3. Настройка MTU

| Тип оверлея | Overhead | Рекомендуемый MTU |
| :--- | :--- | :--- |
| VXLAN | 50 байт | 1450 |
| Geneve | 50 байт | 1450 |
| IPIP | 20 байт | 1480 |
| WireGuard | 60 байт | 1440 |
| IPsec | 50-73 байт | 1400-1420 |

```bash
# Проверка текущего MTU
ip link show | grep -E 'mtu|cali'

# Настройка для Cilium
helm upgrade cilium cilium/cilium --set mtu=1450
```

### 4. Native routing вместо overlay

**Преимущества:**
- Отсутствие overhead инкапсуляции (50 байт)
- Полный MTU 1500
- Прямая видимость подов из физической сети
- Снижение нагрузки на CPU (до 15-20%)

```yaml
# Cilium Helm values
routingMode: native
autoDirectNodeRoutes: true
bgpControlPlane:
  enabled: true
```

### 5. eBPF ускорение (Cilium)

```bash
# XDP для DDoS-защиты
helm upgrade cilium cilium/cilium \
  --set devices='{eth0}' \
  --set xdp.enabled=true

# SOCKMAP для снижения latency (15-20%)
helm upgrade cilium cilium/cilium \
  --set sockops.enabled=true
```

### 6. Bandwidth Manager (Cilium)

```yaml
apiVersion: "cilium.io/v2"
kind: CiliumNetworkPolicy
metadata:
  name: "bandwidth-limit"
spec:
  endpointSelector:
    matchLabels:
      app: my-app
  egress:
  - toEndpoints:
    - matchLabels:
        app: external-service
    toPorts:
    - ports:
      - port: "443"
        protocol: TCP
    bandwidth:
      rate: "10Mbit"
```

### 7. Оптимизация kube-proxy

```bash
# Увеличение интервала синхронизации
kubectl -n kube-system get configmap kube-proxy -o yaml | \
  sed 's/syncPeriod: 30s/syncPeriod: 60s/' | \
  kubectl apply -f -

kubectl -n kube-system rollout restart daemonset/kube-proxy
```

### 8. Оптимизация DNS

```bash
# Установка NodeLocal DNSCache
kubectl apply -f https://raw.githubusercontent.com/kubernetes/kubernetes/refs/heads/master/cluster/addons/dns/nodelocaldns/nodelocaldns.yaml
```

---

## Диагностика

### Инструменты

| Инструмент | Назначение |
| :--- | :--- |
| `iperf3` | Тест пропускной способности |
| `ss` | Статистика сокетов |
| `nstat` | Статистика ядра |
| `ethtool` | Настройка NIC |
| `bpftool` | Диагностика eBPF |
| `hubble` | Видимость трафика Cilium |

### Типичные проблемы

| Проблема | Решение |
| :--- | :--- |
| Высокий CPU от сети | Перейти на IPVS/eBPF; увеличить syncPeriod |
| conntrack table full | Увеличить `nf_conntrack_max` |
| MTU mismatch | Настроить MTU во всех компонентах |
| DNS latency | Установить NodeLocal DNSCache |
| Высокая задержка | Native routing; topology-aware routing |

---

## Рекомендации для production

1. **conntrack:** Мониторьте использование, алерты на 80% от max
2. **MTU:** Согласуйте на всех интерфейсах, учитывая overhead оверлея
3. **Native routing:** Используйте при наличии BGP-инфраструктуры
4. **eBPF:** Рассмотрите Cilium для максимальной производительности
5. **NodeLocal DNSCache:** Установите в каждом production-кластере
6. **kube-proxy:** Увеличьте syncPeriod при большом количестве сервисов

---

## См. также

- [kube-proxy](./kube-proxy.md) — режимы работы и оптимизация
- [Cilium: eBPF CNI](./cilium.md) — eBPF-ускорение
- [IPVS в Kubernetes](./ipvs.md) — высокопроизводительная балансировка

**[К списку разделов CNI](../cni_kube_proxy_roles.md)**
