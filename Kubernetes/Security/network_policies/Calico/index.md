# Calico HostEndpoint and GlobalNetworkPolicy

> Основная документация: [NetworkPolicy](../../network_policies.md)

## Definitions

**HostEndpoint** — ресурс Calico, представляющий один или несколько сетевых интерфейсов на узле Kubernetes. Позволяет применять политики к трафику узла до достижения уровня подов, создавая **периметральный файрвол** кластера.

**GlobalNetworkPolicy** — кластерная сетевая политика Calico, применяемая ко всем namespace'ам. В отличие от стандартного `NetworkPolicy`, поддерживает:

- Селекторы на уровне узлов (`HostEndpoint`)
- Приоритеты (`order`)
- Применение до NAT (`preDNAT`)
- Логирование заблокированного трафика

**Felix** — агент Calico, работающий на каждом узле и применяющий сетевые политики через `iptables` или `eBPF`.

---

## Basic Concepts

### Поведение по умолчанию: Deny All

> **Важно:** При создании `HostEndpoint` для интерфейса Calico немедленно применяет правило **"запретить весь трафик"**. Требуется осторожность: сначала создайте разрешающие правила, затем применяйте `HostEndpoint`.

### Failsafe Ports

Механизм `Failsafe Ports` оставляет открытыми критически важные порты независимо от политик:

| Направление | Порты | Назначение |
|-------------|-------|------------|
| **Inbound** | 22 (SSH), 179 (BGP), 6443 (K8s API), 2379, 2380 (etcd) | Управление кластером |
| **Outbound** | 53 (DNS), 67 (DHCP) | Сетевая инфраструктура |

**Кастомизация:** Через `FelixConfiguration`:

```yaml
apiVersion: projectcalico.org/v3
kind: FelixConfiguration
metadata:
  name: default
spec:
  failsafeInboundHostPorts:
  - protocol: TCP
    port: 22
  - protocol: TCP
    port: 6443
  failsafeOutboundHostPorts:
  - protocol: UDP
    port: 53
```

### Политики `preDNAT`

Для фильтрации трафика до NAT (NodePort, LoadBalancer) используются флаги:

| Флаг | Описание |
|------|----------|
| `preDNAT: true` | Правила `ingress` применяются до DNAT в цепочке `iptables` |
| `applyOnForward: true` | Правила применяются к транзитному трафику (для подов) |

> **Важно:** При `preDNAT: true` требуется **явная политика с `action: Deny`** в конце цепочки для блокировки неразрешённого трафика.

### Приоритеты политик (`order`)

Политики применяются по возрастанию `order`:

- Меньший `order` → раньше применяется
- Политики с одинаковым `order` → аддитивны (объединяются)

---

## Practical Scenarios

Практические сценарии описаны в отдельном файле: [Сценарии Calico](./scenarios.md) — периметральный файрвол, системный трафик, логирование.

Операции обслуживания: [Операции Calico](./operations.md) — troubleshooting, проверка состояния, eBPF, совместимость.

---

## Additional Information

### Связанные ресурсы

Стандартные NetworkPolicy: [Сетевая изоляция и NetworkPolicy](../../../Networking/Network/NetworkPolicy/definitions.md). Роли CNI и kube-proxy: [CNI и kube-proxy](../../../Networking/Network/CNI/definitions.md). Внешние файрволы: [Интеграция внешних файрволов](../../external_firewall_integration.md). Официальная документация: [Calico Documentation](https://docs.tigera.io/calico/latest/).
