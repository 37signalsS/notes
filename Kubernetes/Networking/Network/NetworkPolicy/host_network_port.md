# NetworkPolicy для hostNetwork и hostPort

## Определения

**hostNetwork** — режим работы пода, при котором он использует сетевой стек (network namespace) узла напрямую, минуя виртуальные интерфейсы (veth-pair). Под получает IP-адрес узла и может слушать порты узла напрямую. NetworkPolicy **не применяется** к трафику таких подов на входе, так как трафик не проходит через CNI datapath.

**hostPort** — параметр контейнера, пробрасывающий порт узла на порт контейнера. Реализуется через kube-proxy DNAT. В отличие от hostNetwork, под по-прежнему использует свой network namespace; hostPort работает через DNAT-правила iptables/nftables.

**hostEndpoint** — ресурс Calico, позволяющий применять NetworkPolicy к сетевому интерфейсу хоста (`eth0`). Позволяет защитить узел от внешних атак и фильтровать трафик hostNetwork-подов.

**privileged** — режим контейнера, дающий полный доступ к устройствам хоста и сетевому стеку. Часто используется вместе с hostNetwork для системных компонентов.

## Базовые Концепции

### Взаимодействие hostNetwork с NetworkPolicy

```
┌─────────────────────────────────────────────────────────┐
│ УЗЕЛ (Node)                                              │
│ ┌─────────────────────────────────────────────────────┐  │
│ │ network namespace ХОСТА                            │  │
│ │  ┌───────────────────────────────────────────────┐  │  │
│ │  │ hostNetwork Pod                              │  │  │
│ │  │ (Использует eth0 узла)                       │  │  │
│ │  │ └─ NetworkPolicy: НЕ ПРИМЕНЯЕТСЯ            │  │  │
│ │  └───────────────────────────────────────────────┘  │  │
│ │                                                     │  │
│ │  ┌───────────────────────────────────────────────┐  │  │
│ │  │ Обычный Pod                                  │  │  │
│ │  │ (veth-pair → network namespace пода)         │  │  │
│ │  │ └─ NetworkPolicy: ПРИМЕНЯЕТСЯ               │  │  │
│ │  └───────────────────────────────────────────────┘  │  │
│ └─────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
```

### Взаимодействие hostPort с NetworkPolicy

```
Клиент → УЗЕЛ:NodePort → kube-proxy DNAT → Pod:hostPort → Pod container
                          ↑
                   NetworkPolicy проверяется
                   на этапе DNAT (depends on CNI)
```

hostPort обрабатывается через DNAT-правила kube-proxy. NetworkPolicy фильтрует трафик после DNAT (когда пакет уже направлен на IP пода). Поэтому hostPort работает с NetworkPolicy, но требует разрешения порта в политике.

### Сравнение hostNetwork и hostPort

| Параметр | hostNetwork | hostPort |
| :--- | :--- | :--- |
| **Network namespace** | Хоста | Пода |
| **IP-адрес** | IP узла | IP пода |
| **NetworkPolicy** | Не применяется | Применяется |
| **Порты** | Прямой доступ к портам хоста | DNAT с порта хоста на порт пода |
| **Безопасность** | Низкая (минимальная изоляция) | Средняя (DNAT изоляция) |
| **Производительность** | Максимальная (без overhead) | Высокая (DNAT overhead) |
| **Использование** | Ingress Controller, CNI, kube-proxy | DaemonSet-компоненты |

## Практические сценарии

### Сценарий 1: hostNetwork Ingress Controller + NetworkPolicy

Если Ingress Controller работает с `hostNetwork: true`, его трафик не фильтруется NetworkPolicy. Фильтрация происходит только на стороне целевого пода:

```yaml
# Ingress Controller с hostNetwork (не фильтруется NetworkPolicy)
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: nginx-ingress
  namespace: ingress-nginx
spec:
  selector:
    matchLabels:
      app: nginx-ingress
  template:
    metadata:
      labels:
        app: nginx-ingress
    spec:
      hostNetwork: true  # ← Не фильтруется NetworkPolicy
      containers:
      - name: nginx
        ports:
        - containerPort: 80
          hostPort: 80
        - containerPort: 443
          hostPort: 443

---
# NetworkPolicy для целевых подов (применяется!)
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-from-ingress
  namespace: production
spec:
  podSelector: {}
  policyTypes:
  - Ingress
  ingress:
  - from:
    # Разрешить от всех подов (hostNetwork pod не виден как pod)
    - ipBlock:
        cidr: 0.0.0.0/0
    ports:
    - protocol: TCP
      port: 8080
```

### Сценарий 2: hostPort DaemonSet + NetworkPolicy

DaemonSet с hostPort требует явного разрешения в NetworkPolicy:

```yaml
# DaemonSet с hostPort
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: node-exporter
  namespace: monitoring
spec:
  selector:
    matchLabels:
      app: node-exporter
  template:
    spec:
      containers:
      - name: node-exporter
        ports:
        - containerPort: 9100
          hostPort: 9100  # ← DNAT через kube-proxy

---
# NetworkPolicy для node-exporter
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-prometheus-scrape
  namespace: monitoring
spec:
  podSelector:
    matchLabels:
      app: node-exporter
  policyTypes:
  - Ingress
  ingress:
  - from:
    - namespaceSelector:
        matchLabels:
          kubernetes.io/metadata.name: monitoring
      podSelector:
        matchLabels:
          app: prometheus
    ports:
    - protocol: TCP
      port: 9100
```

### Сценарий 3: hostEndpoint (Calico) для фильтрации hostNetwork

Calico позволяет применять NetworkPolicy к интерфейсу хоста:

```yaml
# HostEndpoint для фильтрации трафика хоста
apiVersion: projectcalico.org/v3
kind: HostEndpoint
metadata:
  name: worker-1-eth0
  labels:
    node: worker-1
spec:
  node: worker-1
  interfaceName: eth0
  expectedIPs:
  - 10.0.0.11
---
# GlobalNetworkPolicy для фильтрации hostNetwork трафика
apiVersion: projectcalico.org/v3
kind: GlobalNetworkPolicy
metadata:
  name: deny-host-network-ingress
spec:
  order: 100
  selector: "node == 'worker-1'"
  types:
  - Ingress
  ingress:
  - action: Deny
    protocol: TCP
    destination:
      ports: [22]  # Блокировка SSH на узле
  - action: Allow
    protocol: TCP
    destination:
      ports: [80, 443]
```

## Дополнительная информация

### Типичные ошибки

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| hostNetwork pod не блокируется NetworkPolicy | Это ожидаемое поведение | Использовать hostEndpoint (Calico) |
| hostPort pod не слушает | DNAT не настроен | Проверить kube-proxy, `iptables -t nat -L` |
| Конфликт портов hostPort | Другой pod уже использует порт | `ss -ltnp \| grep :<port>` |
| hostNetwork pod не виден в NetworkPolicy | Pod не имеет veth-pair | Использовать hostEndpoint |

### Рекомендации

| Сценарий | Рекомендация |
| :--- | :--- |
| **Ingress Controller** | Использовать hostNetwork для производительности, фильтровать на стороне подов |
| **node_exporter** | Использовать hostPort, разрешить в NetworkPolicy |
| **CNI-компоненты** | hostNetwork обязателен (Calico, Cilium работают на уровне хоста) |
| **Системные DaemonSets** | Минимизировать использование hostNetwork; предпочитать hostPort |

### См. также

* [NetworkPolicy: Определения и концепции](./definitions.md) — базовые термины
* [NetworkPolicy: Реализация CNI-плагинами](./cni_implementation.md) — hostEndpoint
* [CNI и kube-proxy](../cni_kube_proxy_roles.md) — DNAT и hostPort
