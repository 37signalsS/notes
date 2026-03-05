# Calico HostEndpoint и GlobalNetworkPolicy

> Основная документация: [NetworkPolicy](../network_policies.md)

## Определения

**HostEndpoint** — ресурс Calico, представляющий один или несколько сетевых интерфейсов на узле Kubernetes. Позволяет применять политики к трафику узла до достижения уровня подов, создавая **периметральный файрвол** кластера.

**GlobalNetworkPolicy** — кластерная сетевая политика Calico, применяемая ко всем namespace'ам. В отличие от стандартного `NetworkPolicy`, поддерживает:

- Селекторы на уровне узлов (`HostEndpoint`)
- Приоритеты (`order`)
- Применение до NAT (`preDNAT`)
- Логирование заблокированного трафика

**Felix** — агент Calico, работающий на каждом узле и применяющий сетевые политики через `iptables` или `eBPF`.

## Основные концепции

### Поведение по умолчанию: Deny All

> **Важно:** При создании `HostEndpoint` для интерфейса Calico немедленно применяет правило **"запретить весь трафик"**. Требуется осторожность: сначала создайте разрешающие правила, затем применяйте `HostEndpoint`.

### Failsafe Ports (Защита от блокировки)

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

## Практические сценарии

### Сценарий 1: Периметральный файрвол кластера

**Задача:**

1. Разрешить исходящий трафик полностью
2. Разрешить входящий от подов и между узлами
3. Разрешить доступ к LoadBalancer IP и Kubernetes API
4. Запретить остальной входящий трафик

#### Шаг 1: Создание HostEndpoint для узлов

```yaml
# host-endpoints.yaml
apiVersion: projectcalico.org/v3
kind: HostEndpoint
metadata:
  name: control-node-1-ens160
  labels:
    node-role: control-plane
    node-endpoint-type: home-cluster
spec:
  interfaceName: ens160
  node: control-node-1.example.local
  expectedIPs: ["192.168.218.171"]
---
apiVersion: projectcalico.org/v3
kind: HostEndpoint
metadata:
  name: worker-node-1-ens160
  labels:
    node-role: worker
    node-endpoint-type: home-cluster
spec:
  interfaceName: ens160
  node: worker-node-1.example.local
  expectedIPs: ["192.168.218.175"]
```

> **Примечание:** Для получения имени узла: `kubectl get nodes -o wide`. Для IP интерфейса: `ip addr show ens160`.

#### Шаг 2: Разрешающая политика (order: 10)

```yaml
# allow-traffic-policy.yaml
apiVersion: projectcalico.org/v3
kind: GlobalNetworkPolicy
metadata:
  name: allow-cluster-traffic
spec:
  order: 10
  selector: "has(node-endpoint-type)"
  preDNAT: true
  applyOnForward: true
  types:
    - Ingress
    - Egress
  egress:
    - action: Allow
  ingress:
    # Трафик от подов
    - action: Allow
      source:
        nets: ["10.233.0.0/16"]  # Замените на ваш Pod CIDR
    # Трафик между узлами
    - action: Allow
      source:
        selector: "has(node-endpoint-type)"
    # Доступ к Ingress
    - action: Allow
      destination:
        nets: ["192.168.218.180/32"]
        ports: [80, 443]
    # Доступ к Kubernetes API
    - action: Allow
      destination:
        nets: ["192.168.218.189/32"]
        ports: [7443]
```

#### Шаг 3: Запрещающая политика (order: 20)

```yaml
# default-deny-policy.yaml
apiVersion: projectcalico.org/v3
kind: GlobalNetworkPolicy
metadata:
  name: default-deny
spec:
  order: 20
  selector: "has(node-endpoint-type)"
  preDNAT: true
  applyOnForward: true
  types:
    - Ingress
  ingress:
    - action: Deny
```

#### Шаг 4: Применение

```bash
kubectl apply -f allow-traffic-policy.yaml
kubectl apply -f default-deny-policy.yaml
kubectl apply -f host-endpoints.yaml
```

### Сценарий 2: Разрешение только системного трафика

Минимальная конфигурация для новых узлов:

```yaml
apiVersion: projectcalico.org/v3
kind: GlobalNetworkPolicy
metadata:
  name: allow-system-traffic
spec:
  order: 5
  selector: "has(node-endpoint-type)"
  preDNAT: true
  applyOnForward: true
  types: [Ingress, Egress]
  egress:
    - action: Allow
  ingress:
    # BGP между узлами (для Calico)
    - action: Allow
      protocol: TCP
      destination:
        ports: [179]
      source:
        nets: ["10.0.0.0/8"]  # Внутренняя сеть
    # Kubernetes API
    - action: Allow
      protocol: TCP
      destination:
        ports: [6443, 7443]
```

### Сценарий 3: Логирование заблокированного трафика

Для отладки политик включите логирование denied-трафика:

```yaml
apiVersion: projectcalico.org/v3
kind: GlobalNetworkPolicy
metadata:
  name: log-denied-traffic
spec:
  order: 1000
  selector: "has(node-endpoint-type)"
  types: [Ingress, Egress]
  ingress:
    - action: Log
      log:
        logPrefix: "calico-denied-ingress:"
    - action: Deny
  egress:
    - action: Log
      log:
        logPrefix: "calico-denied-egress:"
    - action: Deny
```

**Просмотр логов:** `journalctl -u calico-node -f | grep "calico-denied"`

## Дополнительная информация

### Известные проблемы

#### NodePort фильтрация

Трафик на `NodePort` может обходить политики из-за:

- Особенностей реализации в `iptables`
- Порядка применения правил до/после DNAT

**Временное решение:**

- Использовать `preDNAT: true` + явные правила для портов NodePort
- Рассмотреть `LoadBalancer` вместо `NodePort`
- Использовать `eBPF` режим Calico (более предсказуемое поведение)

#### Изменение IP узлов

При изменении IP узла требуется обновить `expectedIPs` в `HostEndpoint`:

```bash
calicoctl get hostendpoint <name> -o yaml | \
  sed 's/old-ip/new-ip/' | \
  calicoctl apply -f -
```

### Проверка состояния

```bash
# Список HostEndpoint
calicoctl get hostendpoints -o wide

# Детали конкретного HostEndpoint
calicoctl get hostendpoint <name> -o yaml

# Применённые политики
calicoctl get globalnetworkpolicy -o wide

# Статус Felix (на узле)
calicoctl node status
```

### Troubleshooting

| Проблема | Возможная причина | Решение |
|----------|-------------------|---------|
| Блокировка SSH после применения | Отсутствует `node-endpoint-type` метка | Добавить метку, применить политику до HostEndpoint |
| NodePort не фильтруется | `preDNAT: false` | Установить `preDNAT: true` |
| BGP не работает | Блокировка порта 179 | Разрешить BGP в политике |
| DNS не работает | Блокировка outbound 53 | Добавить egress правило для DNS |

### Совместимость версий

| Calico | Kubernetes | Статус |
|--------|------------|--------|
| v3.28.x | 1.28–1.31 | ⚠️ Проверить |
| v3.31.x | 1.28–1.32 | ✅ Рекомендуется |

> **Важно:** Всегда проверяйте [официальную матрицу совместимости](https://docs.tigera.io/calico/latest/about/supported-releases).

### eBPF режим

Calico поддерживает режим `eBPF` для замены `iptables`:

**Преимущества:**

- Выше производительность
- Предсказуемое поведение с NodePort
- Встроенная замена `kube-proxy`

**Включение:**

```yaml
# В calico-config ConfigMap
- name: FELIX_BPFENABLED
  value: "true"
```

### Связанные темы

- Стандартные NetworkPolicy: [Сетевая Изоляция и NetworkPolicy](../../Networking/Network/network_policy.md)
- CNI и kube-proxy: [Роли CNI и kube-proxy](../../Networking/Network/cni_kube_proxy_roles.md)
- Сетевая модель: [Обзор сети Kubernetes](../../Networking/Network/network_overview.md)
- Официальная документация: [Calico Documentation](https://docs.tigera.io/calico/latest/)
