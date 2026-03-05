# Сценарии Calico: периметральный файрвол

## Определения

**Сценарии Calico** — практические случаи использования HostEndpoint и GlobalNetworkPolicy для защиты кластера Kubernetes.

> **Навигация:** [Главная Calico](./index.md) | [Операции](./operations.md)

---

## Practical Scenarios

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

---

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

---

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

---

## Additional Information

### Связанные темы

- **[NetworkPolicy](../network_policies.md)** — стандартные NetworkPolicy
- **[Сетевая Изоляция](../../Networking/Network/network_policy.md)** — сетевая изоляция
