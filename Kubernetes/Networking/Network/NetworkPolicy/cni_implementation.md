# NetworkPolicy: Реализация CNI-плагинами

## Определения

**CNI (Container Network Interface) плагин с поддержкой NetworkPolicy** — сетевой плагин Kubernetes, который реализует не только базовую IP (Internet Protocol) связность между Pod (подами), но и фильтрацию трафика согласно правилам `NetworkPolicy`.

**Критически важно:** NetworkPolicy работает только при наличии CNI-плагина с поддержкой этой функциональности. Если CNI не поддерживает NetworkPolicy (например, Flannel), созданные правила **не будут применены** — трафик продолжит проходить свободно.

## Базовые Концепции

### Базовый стандарт Kubernetes

Все CNI с поддержкой NetworkPolicy реализуют **единый стандарт** Kubernetes:

- **Селекторы:** `podSelector`, `namespaceSelector`, `ipBlock`
- **Протоколы:** TCP (Transmission Control Protocol), UDP (User Datagram Protocol), SCTP (Stream Control Transmission Protocol)
- **policyTypes:** Ingress (входящий трафик), Egress (исходящий трафик)

### Поддержка NetworkPolicy различными CNI

| CNI | Поддержка NetworkPolicy | Примечания |
|-----|------------------------|------------|
| **Calico** | Полная | Расширения: HostEndpoint, GlobalNetworkPolicy, логирование, ICMP (Internet Control Message Protocol) |
| **Cilium** | Полная | Расширения: L7-политики, FQDN (Fully Qualified Domain Name) фильтрация, eBPF (Extended Berkeley Packet Filter) |
| **Weave Net** | Полная | Базовая поддержка |
| **Flannel** | Нет | Только связность Pod, без политик |
| **Kube-router** | Полная | На основе iptables |
| **Antrea** | Полная | На основе Open vSwitch |

## Практические Сценарии

### Выбор CNI для NetworkPolicy

| Требование | Рекомендуемый CNI |
|------------|-------------------|
| Базовая изоляция Namespace | Calico, Cilium, Weave Net |
| Логирование заблокированного трафика | Calico |
| L7-фильтрация (HTTP, gRPC) | Cilium |
| Политики для нод кластера | Calico (HostEndpoint) |
| Кластерные политики (multi-namespace) | Calico (GlobalNetworkPolicy) |
| FQDN-фильтрация внешних запросов | Cilium |
| Максимальная производительность | Cilium (eBPF), Calico (BGP) |

*HTTP (HyperText Transfer Protocol), gRPC (Google Remote Procedure Call), BGP (Border Gateway Protocol).*

### Миграция с Flannel на Calico/Cilium

Если вы используете Flannel и требуется NetworkPolicy:

1. Установите новый CNI (Calico или Cilium) через Helm или манифесты.
2. Дождитесь готовности Pod нового CNI в системном пространстве имен `kube-system`.
3. Удалите DaemonSet (набор демонов) Flannel.
4. Пересоздайте Pod приложений для применения новых сетевых политик.

## Дополнительные Сведения

### Расширения CNI (vendor-specific)

#### Calico

- **`HostEndpoint`** — политики для интерфейсов узлов.
- **`GlobalNetworkPolicy`** — кластерные политики вне Namespace.
- **`preDNAT`** — фильтрация до выполнения NAT (Network Address Translation) для NodePort или LoadBalancer.
- **Логирование заблокированного трафика** — помогает при отладке.
- **Блокировка ICMP** — расширенный контроль протоколов.

#### Cilium

- **L7-политики** — фильтрация на уровне приложений (HTTP, gRPC, Kafka).
- **FQDN-фильтрация** — политики на основе DNS (Domain Name System) для контроля внешних запросов.
- **Identity-based политики** — идентификация на основе меток безопасности.
- **eBPF-ускорение** — высокая производительность фильтрации.

### Архитектурные различия

**Calico** использует BGP для маршрутизации и iptables или eBPF для фильтрации. Поддерживает как режим с инкапсуляцией (IPIP/VXLAN), так и прямую маршрутизацию.

**Cilium** построен на eBPF и обеспечивает фильтрацию на уровне ядра без накладных расходов iptables. Требует ядро Linux 4.19+ для полной функциональности.

**Weave Net** использует оверлейную сеть на основе VXLAN и реализует базовую поддержку NetworkPolicy через iptables.

* **Лучшие практики**: [NetworkPolicy: Лучшие практики](./best_practices.md)
* **Базовые концепции**: [NetworkPolicy: Определения и концепции](./definitions.md)
* **Роль CNI**: [Сетевые плагины: Определения](../CNI/definitions.md)
* **Calico HostEndpoint и GlobalNetworkPolicy**: [../../Security/network_policies/Calico/index.md](../../Security/network_policies/Calico/index.md)
