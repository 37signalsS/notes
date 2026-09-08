# NetworkPolicy для bare metal и on-premise сред

## Определения

**Bare Metal** — физические серверы без виртуализации со стороны облачного провайдера. В Kubernetes bare metal кластеры используют MetalLB, BGP-маршрутизацию или внешние балансировщики для предоставления LoadBalancer-сервисов.

**On-Premise (On-Prem)** — локальная инфраструктура, расположенная в собственном ЦОД организации. Включает bare metal серверы, виртуальные машины и гибридные конфигурации.

**BGP (Border Gateway Protocol)** — протокол маршрутизации, используемый Calico для анонсирования Pod CIDR во внешнюю сеть. В bare metal средах BGP позволяет достичь прямой маршрутизации (native routing) без инкапсуляции.

**MetalLB** — решение для предоставления LoadBalancer-сервисов в bare metal Kubernetes-кластерах. Работает в режимах L2 (ARP-announce) и BGP.

**VRRP (Virtual Router Redundancy Protocol)** — протокол обеспечения отказоустойчивости шлюза. Используется MetalLB в L2-режиме для предоставления виртуального IP-адреса.

## Базовые Концепции

### Отличия NetworkPolicy в bare metal от облачных сред

| Фактор | Облачная среда | Bare metal / On-prem |
| :--- | :--- | :--- |
| **Внешний LB** | Cloud LB (AWS ELB, GCP LB) | MetalLB, HAProxy, внешний LB |
| **BGP** | Управляемый провайдером | Настройка Calico BGP manually |
| **IP-пул Pod CIDR** | Управляемый CCM | Статическая конфигурация |
| **MTU** | Обычно 1500 (без overlay) | 1450 (VXLAN) или 1500 (native) |
| **hostNetwork** | Редко используется | Распространено для Ingress |
| **Доступ к metadata API** | 169.254.169.254 | Отсутствует или другой URL |

### Архитектура NetworkPolicy в bare metal

```
┌─────────────────────────────────────────────────────────┐
│                     Физическая сеть                      │
│ ┌─────────────┐  ┌─────────────┐  ┌─────────────┐       │
│ │   Узел 1    │  │   Узел 2    │  │   Узел 3    │       │
│ │ Calico BGP  │  │ Calico BGP  │  │ Calico BGP  │       │
│ │ (AS 65001)  │  │ (AS 65001)  │  │ (AS 65001)  │       │
│ └──────┬──────┘  └──────┬──────┘  └──────┬──────┘       │
│        │                │                │               │
│        └────────┬───────┴────────┬───────┘               │
│                 │  BGP peering   │                       │
│                 ▼                ▼                       │
│        ┌────────────────────────────────┐               │
│        │     Внешний маршрутизатор      │               │
│        │     (BGP peer, AS 65000)       │               │
│        └────────────────────────────────┘               │
└─────────────────────────────────────────────────────────┘
```

## Практические сценарии

### Сценарий 1: Calico BGP + NetworkPolicy

Настройка Calico для прямой маршрутизации Pod CIDR в bare metal:

```yaml
# 1. IPPool с BGP (без инкапсуляции)
apiVersion: projectcalico.org/v3
kind: IPPool
metadata:
  name: pod-ipv4-pool
spec:
  cidr: 10.244.0.0/16
  encapsulation: None  # Native routing
  natOutgoing: true
  nodeSelector: all()
---
# 2. BGP Configuration
apiVersion: projectcalico.org/v3
kind: BGPConfiguration
metadata:
  name: default
spec:
  logSeverityScreen: Info
  nodeToNodeMeshEnabled: true
  asNumber: 65001
---
# 3. NetworkPolicy для bare metal
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-bgp-routes
  namespace: production
spec:
  podSelector: {}
  policyTypes:
  - Ingress
  ingress:
  - from:
    # Разрешить трафик от других узлов (BGP)
    - ipBlock:
        cidr: 10.0.0.0/8
    ports:
    - protocol: TCP
      port: 8080
```

### Сценарий 2: MetalLB + NetworkPolicy

```yaml
# 1. MetalLB IP-pool
apiVersion: metallb.io/v1beta1
kind: IPAddressPool
metadata:
  name: production-pool
  namespace: metallb-system
spec:
  addresses:
  - 192.168.1.100-192.168.1.200
---
# 2. L2 advertisement
apiVersion: metallb.io/v1beta1
kind: L2Advertisement
metadata:
  name: production-l2
  namespace: metallb-system
spec:
  ipAddressPools:
  - production-pool
---
# 3. NetworkPolicy для LoadBalancer сервиса
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-metallb-access
  namespace: production
spec:
  podSelector:
    matchLabels:
      app: my-app
  policyTypes:
  - Ingress
  ingress:
  - from:
    # Все поды в metallb-system
    - namespaceSelector:
        matchLabels:
          kubernetes.io/metadata.name: metallb-system
    # Все поды в сети (внешние клиенты)
    - ipBlock:
        cidr: 192.168.1.0/24
    ports:
    - protocol: TCP
      port: 8080
```

### Сценарий 3: NetworkPolicy для kube-system в bare metal

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-kube-system-internal
  namespace: kube-system
spec:
  podSelector: {}
  policyTypes:
  - Ingress
  - Egress
  ingress:
  # API Server
  - ports:
    - protocol: TCP
      port: 6443
  # kubelet
  - ports:
    - protocol: TCP
      port: 10250
  egress:
  # DNS
  - ports:
    - protocol: UDP
      port: 53
  # Все поды в кластере (для компонентов kube-system)
  - to:
    - namespaceSelector: {}
    ports:
    - protocol: TCP
      port: 10250
```

## Дополнительная информация

### Типичные проблемы bare metal + NetworkPolicy

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| Pod CIDR не маршрутизируется | BGP не настроен или network не поддерживает BGP | Настроить BGP peering или использовать VXLAN |
| LoadBalancer не получает IP | MetalLB не установлен или IP-пул исчерпан | Установить MetalLB, проверить IPAddressPool |
| Внешний трафик не проходит | NetworkPolicy не разрешает IP-адреса сети | Добавить `ipBlock` с CIDR физической сети |
| MTU mismatch | VXLAN overhead (50 байт) не учтен | Установить MTU 1450 для VXLAN или 1500 для native |
| hostNetwork pod не фильтруется | NetworkPolicy не применяется к hostNetwork | Использовать hostEndpoint (Calico) |

### Рекомендации по bare metal

| Параметр | Рекомендация |
| :--- | :--- |
| **CNI** | Calico с BGP для native routing |
| **MTU** | 1450 для VXLAN, 1500 для native |
| **BGP AS** | Один AS для всего кластера (mesh) |
| **MetalLB** | L2 для небольших кластеров, BGP для больших |
| **hostNetwork** | Использовать для Ingress Controller с hostPort |

### См. также

* [MetalLB](../../metallb.md) — балансировщик для bare metal
* [NetworkPolicy: Реализация CNI-плагинами](./cni_implementation.md) — Calico BGP
* [NetworkPolicy: Egress паттерны](./egress_patterns.md) — Egress Gateway
