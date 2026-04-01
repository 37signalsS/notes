# NetworkPolicy: Реализация CNI-плагинами

## Определения

**CNI-плагин с поддержкой NetworkPolicy** — сетевой плагин Kubernetes, который реализует не только базовую IP-связность между подами, но и фильтрацию трафика согласно правилам `NetworkPolicy`.

**Критически важно:** NetworkPolicy работает только при наличии CNI-плагина с поддержкой этой функциональности. Если CNI не поддерживает NetworkPolicy (например, Flannel), созданные правила **не будут применены** — трафик продолжит проходить свободно.

## Базовые Концепции

### Базовый стандарт Kubernetes

Все CNI с поддержкой NetworkPolicy реализуют **единый стандарт** Kubernetes:

- **Селекторы:** `podSelector`, `namespaceSelector`, `ipBlock`
- **Протоколы:** TCP, UDP, SCTP
- **policyTypes:** Ingress, Egress

### Поддержка NetworkPolicy различными CNI

| CNI | Поддержка NetworkPolicy | Примечания |
|-----|------------------------|------------|
| **Calico** | ✅ Полная | Расширения: HostEndpoint, GlobalNetworkPolicy, логирование, ICMP |
| **Cilium** | ✅ Полная | Расширения: L7-политики, FQDN-фильтрация, eBPF |
| **Weave Net** | ✅ Полная | Базовая поддержка |
| **Flannel** | ❌ Нет | Только связность подов, без политик |
| **Kube-router** | ✅ Полная | На основе iptables |
| **Antrea** | ✅ Полная | На основе Open vSwitch |

## Практические Сценарии

### Выбор CNI для NetworkPolicy

| Требование | Рекомендуемый CNI |
|------------|-------------------|
| Базовая изоляция namespace | Calico, Cilium, Weave Net |
| Логирование заблокированного трафика | Calico |
| L7-фильтрация (HTTP, gRPC) | Cilium |
| Политики для нод кластера | Calico (HostEndpoint) |
| Кластерные политики (multi-namespace) | Calico (GlobalNetworkPolicy) |
| FQDN-фильтрация внешних запросов | Cilium |
| Максимальная производительность | Cilium (eBPF), Calico (BGP) |

### Миграция с Flannel на Calico/Cilium

Если вы используете Flannel и требуется NetworkPolicy:

1. Установите новый CNI (Calico или Cilium) через Helm/manifest
2. Дождитесь готовности подов нового CNI в `kube-system`
3. Удалите DaemonSet Flannel
4. Пересоздайте поды приложений для применения новых сетевых политик

## Дополнительные Сведения

### Расширения CNI (vendor-specific)

#### Calico

- **`HostEndpoint`** — политики для интерфейсов нод
- **`GlobalNetworkPolicy`** — кластерные политики вне namespace
- **`preDNAT`** — фильтрация до NAT (для NodePort/LoadBalancer)
- **Логирование заблокированного трафика** — помогает при отладке
- **Блокировка ICMP** — расширенный контроль протоколов

#### Cilium

- **L7-политики** — фильтрация на уровне приложений (HTTP, gRPC, Kafka)
- **FQDN-фильтрация** — DNS-based политики для контроля внешних запросов
- **Identity-based политики** — идентификация на основе меток безопасности
- **eBPF-ускорение** — высокая производительность фильтрации

### Архитектурные различия

**Calico** использует BGP для маршрутизации и iptables/eBPF для фильтрации. Поддерживает как режим с инкапсуляцией (IPIP/VXLAN), так и прямую маршрутизацию.

**Cilium** построен на eBPF и обеспечивает фильтрацию на уровне ядра без накладных расходов iptables. Требует ядро Linux 4.19+ для полной функциональности.

**Weave Net** использует оверлейную сеть на основе VXLAN и реализует базовую поддержку NetworkPolicy через iptables.

*Подробнее о лучших практиках: [best_practices.md](./best_practices.md)*  
*Подробнее о базовых концепциях: [definitions.md](./definitions.md)*  
*Подробнее о роли CNI: [../CNI/definitions.md](../CNI/definitions.md)*  
*Calico HostEndpoint и GlobalNetworkPolicy: [../../Security/network_policies/Calico/index.md](../../Security/network_policies/Calico/index.md)*
