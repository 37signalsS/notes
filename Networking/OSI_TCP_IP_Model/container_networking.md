# Контейнерный Networking: обзор через призму OSI

## Определения

**CNI (Container Network Interface)** — спецификация (CNCF), определяющая стандартный интерфейс для настройки сетевой-connectivity в контейнерах. CNI-плагин вызывается при создании/удалении контейнера и отвечает за настройку network namespace, veth-пар, IP-адресацию и маршрутизацию.

**Network Namespace** — изолированная область в ядре Linux, содержащая собственный набор сетевых интерфейсов, IP-адресов, таблиц маршрутизации и правил iptables/nftables. Каждый контейнер получает свой network namespace.

**veth pair (Virtual Ethernet)** — виртуальный сетевой кабель. Один конец находится в namespace контейнера, другой — в namespace хоста (или bridge). Трафик, поступающий на один конец, мгновенно появляется на другом.

**Container Bridge (docker0, cbr0)** — виртуальный L2-коммутатор, к которому подключены veth-пары контейнеров. Реализуется через Linux bridge. Обеспечивает L2-связность между контейнерами на одном хосте.

**Overlay Network** — виртуальная сеть, построенная поверх физической (underlay) с помощью инкапсуляции (VXLAN, Geneve, GRE). Позволяет контейнерам на разных хостах обмениваться кадрами с L2-семантикой, как будто они в одном ethernet-сегменте.

**Pod (Kubernetes)** — минимальная deployable-единица. Один Pod = один или несколько контейнеров, разделяющих один network namespace (общий IP-адрес, общие порты).

## Основные концепции

### Сетевая модель контейнера через OSI

```text
L7 (Прикладной)    ← Приложение внутри контейнера (HTTP, gRPC)
L6 (Представления) ← TLS (sidecar или встроенный)
L5 (Сеансовый)     ← Управление сессиями (TCP keepalive, QUIC Connection ID)
L4 (Транспортный)  ← TCP/UDP: контейнер → контейнер (общий network namespace в Pod)
L3 (Сетевой)       ← IP: контейнер → контейнер (через CNI), контейнер → внешний мир (NAT)
L2 (Канальный)     ← veth pair → bridge/overlay (VXLAN/Geneve)
L1 (Физический)    ← Физический NIC хоста
```

### Архитектура CNI: вызов и ответ

```text
kubelet → CRI → containerd → CNI plugin → Настройка сети
                                              │
                                              ├─ Создание network namespace
                                              ├─ Создание veth-пары
                                              ├─ Присоединение к bridge/overlay
                                              ├─ Настройка IP (IPAM)
                                              └─ Настройка маршрутизации/iptables
```

### Типы сетевых топологий контейнеров

#### 1. Bridge-модель (Docker по умолчанию)

```text
┌──────────────┐     ┌──────────────┐
│  Контейнер A  │     │  Контейнер B  │
│  vethA (L3)  │     │  vethB (L3)  │
└──────┬───────┘     └──────┬───────┘
       │                     │
       └─────────┬───────────┘
            ┌────┴────┐
            │  docker0 │  ← Linux Bridge (L2)
            │  (bridge) │
            └────┬────┘
                 │
            ┌────┴────┐
            │  eth0    │  ← Физический NIC
            └─────────┘
```

- **L2-связность:** Контейнеры на одном хосте общаются через bridge.
- **IP-адресация:** Каждый контейнер получает IP из подсети bridge (например, 172.17.0.0/16).
- **NAT для исходящего трафика:** `iptables -t nat -A POSTROUTING -s 172.17.0.0/16 -o eth0 -j MASQUERADE`.
- **Ограничение:** Контейнеры на разных хостах не видят друг друга без NAT/routing.

#### 2. Overlay-модель (Docker Swarm, Kubernetes с Flannel VXLAN)

```text
┌──────────── Хост 1 ────────────┐     ┌──────────── Хост 2 ────────────┐
│  Контейнер A                    │     │  Контейнер B                    │
│  IP: 10.244.1.2                 │     │  IP: 10.244.2.3                 │
└──────────┬─────────────────────┘     └──────────┬─────────────────────┘
           │                                       │
    ┌──────┴──────┐                         ┌──────┴──────┐
    │  cni0/br0   │                         │  cni0/br0   │
    └──────┬──────┘                         └──────┬──────┘
           │                                       │
    ┌──────┴──────┐                         ┌──────┴──────┐
    │ VXLAN (L4)  │ ◄──── UDP:4789 ─────► │ VXLAN (L4)  │
    │ outer IP:   │                         │ outer IP:   │
    │ 192.168.1.10│                         │ 192.168.1.11│
    └─────────────┘                         └─────────────┘
```

- **L2-over-L3:** Кадры контейнеров инкапсулируются в UDP-дейтаграммы (VXLAN) для прохождения через L3-сеть.
- **VTEP (VXLAN Tunnel Endpoint):** Каждый хост имеет VTEP (IP: 192.168.1.10/11), который инкапсулирует/деинкапсулирует кадры.
- **MTU:** Служебный заголовок VXLAN = 50 байт (UDP+IP+VXLAN). Эффективный MTU = 1500 - 50 = 1450 байт.

#### 3. Routed-модель (Calico BGP, Cilium)

```text
┌──────────── Хост 1 ────────────┐     ┌──────────── Хост 2 ────────────┐
│  Контейнер A                    │     │  Контейнер B                    │
│  IP: 10.244.1.2                 │     │  IP: 10.244.2.3                 │
└──────────┬─────────────────────┘     └──────────┬─────────────────────┘
           │                                       │
    ┌──────┴──────┐                         ┌──────┴──────┐
    │ cali0 (veth)│                         │ cali0 (veth)│
    └──────┬──────┘                         └──────┬──────┘
           │                                       │
    ┌──────┴──────┐                         ┌──────┴──────┐
    │  Routing    │ ◄──── BGP/Static ────► │  Routing    │
    │  Table      │                         │  Table      │
    └──────┬──────┘                         └──────┬──────┘
           │                                       │
    ┌──────┴──────┐                         ┌──────┴──────┐
    │  eth0       │                         │  eth0       │
    └─────────────┘                         └─────────────┘
```

- **Без overlay:** Каждый контейнер получает routable IP из пула PodCIDR (например, 10.244.0.0/16).
- **Маршрутизация:** Хосты обмениваются маршрутами через BGP (Calico) или статические маршруты.
- **Производительность:** Нет overhead инкапсуляции (нет额外 заголовков).
- **Требование:** Сеть хостов должна маршрутизировать PodCIDR.

### kube-proxy: реализация Service в Kubernetes

```text
Клиент (Pod) → Service ClusterIP → kube-proxy rules → Backend Pod

Три режима:
1. iptables  — DNAT через цепочки iptables (O(N) поиск)
2. IPVS      — Внутриядерный L4-балансировщик (O(1) поиск)
3. eBPF      — Программы в ядре (Cilium, XDP)
```

| Режим | Механизм | Масштабируемость | Особенности |
| :--- | :--- | :--- | :--- |
| **iptables** | DNAT цепочки | ~5000 Services | Простая настройка, но O(N) |
| **IPVS** | Внутриядерный LB | ~20 000+ Services | RR, WLC, LC, SH алгоритмы |
| **eBPF** | BPF-программы | ~100 000+ Services | O(1), Hubble observability |

### NetworkPolicy: файрвол для Pod'ов

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-frontend-to-backend
spec:
  podSelector:
    matchLabels:
      app: backend
  policyTypes:
    - Ingress
  ingress:
    - from:
        - podSelector:
            matchLabels:
              app: frontend
      ports:
        - protocol: TCP
          port: 8080
```

- **Default behavior:** Если NetworkPolicy не применяется → весь трафик разрешён.
- **Default-deny:** Пустой policy с `policyTypes: [Ingress, Egress]` блокирует всё.
- **Реализация:** Calico (iptables/eBPF), Cilium (eBPF), Flannel (не поддерживает).

## Практические сценарии

### Диагностика сетевых проблем в контейнерах

```bash
# 1. Проверить IP-адрес контейнера
docker inspect <container> | grep IPAddress
kubectl get pod <pod> -o jsonpath='{.status.podIP}'

# 2. Проверить veth-пару
ip link show type veth
bridge link show

# 3. Проверить маршруты
ip route show
ip route get 10.244.2.3

# 4. Проверить conntrack (для NAT)
conntrack -L -p tcp --dport 8080
conntrack -S

# 5. Проверить MTU ( overlay-сети)
ping -M do -s 1472 <target_ip>

# 6. Захват трафика в Pod
kubectl debug -it <pod> --image=nicolaka/netshoot -- tcpdump -i eth0 -nn
```

### Типичные проблемы и решения

| Проблема | Симптомы | Причина | Решение |
| :--- | :--- | :--- | :--- |
| **Pod не пингуется** | `ping: network is unreachable` | CNI не настроен, NetworkPolicy блокирует | Проверить CNI, `kubectl describe networkpolicy` |
| **DNS не работает** | `nslookup: can't resolve` | CoreDNS не доступен, NetworkPolicy | Проверить CoreDNS Pods, `kubectl get svc kube-dns` |
| **Service не балансирует** | Все запросы идут на один Pod | kube-proxy в iptables-режиме, проблема с hash | Переключить на IPVS, проверить `ipvsadm -Ln` |
| **Внутри Pod нет интернета** | `curl: couldn't connect` | NAT не работает, default route | Проверить `ip route`, `iptables -t nat -L` |
| **MTU mismatch** | SSH зависает при `ls`, `df` | Overlay MTU <物理 MTU | Настроить MSS Clamping, `ping -M do` |

### Conntrack в контейнерах

```bash
# Просмотр таблицы conntrack
conntrack -L -p tcp --dport 8080

# Статистика (dropped/invalid)
conntrack -S

# Размер таблицы
sysctl net.netfilter.nf_conntrack_max
sysctl net.netfilter.nf_conntrack_count

# Таймауты (для коротких TCP-соединений)
sysctl net.netfilter.nf_conntrack_tcp_timeout_established  # по умолчанию 432000 (5 дней)
sysctl net.netfilter.nf_conntrack_tcp_timeout_time_wait    # по умолчанию 120
```

## Дополнительная информация

### MTU в overlay-сетях

| Тип overlay | Overhead | Эффективный MTU | Примечание |
| :--- | :--- | :--- | :--- |
| VXLAN | 50 байт | 1450 | Стандарт для Flannel, Docker |
| Geneve | 60-100 байт | 1400-1440 | Универсальный (Cilium) |
| IPsec (Tunnel) | 50-73 байт | 1427-1450 | Шифрование overlay |
| WireGuard | 60-80 байт | 1420-1440 | Шифрование (Cilium) |

Подробнее: **[MTU и VPN](./Network_layer/mtu_and_vpn.md)**.

### CNI-плагины: сравнение

| Плагин | Тип | Поддержка NetworkPolicy | Транспорт | Производительность |
| :--- | :--- | :--- | :--- | :--- |
| **Calico** | Routed/BGP | Да (iptables/eBPF) | IP routing | Высокая |
| **Cilium** | eBPF | Да (eBPF) | eBPF/XDP | Очень высокая |
| **Flannel** | Overlay | Нет (нет Policy) | VXLAN | Средняя |
| **Weave** | Overlay | Да | Sleeve/VXLAN | Средняя |
| **Antrea** | OpenFlow | Да | Geneve/VLAN | Высокая |

Подробнее: **[CNI в Kubernetes](../../Kubernetes/Networking/Network/CNI/selection_and_external_access.md)**, **[eBPF как CNI](../../Kubernetes/Networking/Network/CNI/ebpf.md)**.

### Hairpin NAT в Kubernetes

**Hairpin NAT** — сценарий, когда Pod обращается к Service (ClusterIP), а ответ приходит от того же Pod'а (который является бэкендом этого Service). Без hairpin NAT пакет ушёл бы наружу и вернулся бы с другого IP.

```bash
# Включить hairpin (включено по умолчанию в modern Kubernetes)
sysctl -w net.bridge.bridge-nf-call-iptables=1
sysctl -w net.bridge.bridge-nf-call-ip6tables=1

# Проверить
sysctl net.bridge.bridge-nf-call-iptables
```

Подробнее: **[Service ExternalIPs и Hairpin](../../Kubernetes/Networking/Service/service_externalips.md)**.

### Смотрите также

- **[Модель OSI](./osi_model.md)** — понимание уровней для диагностики.
- **[Модель TCP/IP](./tcp_ip_model.md)** — практический стек протоколов.
- **[Транспортный уровень (L4)](./transport_layer.md)** — TCP/UDP в контексте контейнеров.
- **[Сетевой уровень (L3)](./Network_layer/Concepts/network_layer_overview.md)** — IP-адресация, маршрутизация.
- **[MTU и VPN](./Network_layer/mtu_and_vpn.md)** — расчёт MTU для overlay-сетей.
- **[NAT и conntrack](../Concepts/nat/overview.md)** — NAT в контейнерах.
- **[eBPF/XDP](../Concepts/sdn/ebpf_xdp.md)** — высокопроизводительный networking.
- **[CNI в Kubernetes](../../Kubernetes/Networking/Network/CNI/selection_and_external_access.md)** — выбор CNI-плагина.
- **[NetworkPolicy в Kubernetes](../../Kubernetes/Networking/Network/NetworkPolicy/definitions.md)** — файрвол для Pod'ов.
- **[Service Mesh](../../Service_Mesh/service_mesh_concepts.md)** — L7-балансировка и mTLS между Pod'ами.
