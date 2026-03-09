# NetworkPolicy: управление трафиком между Pod'ами

> Полное руководство с пошаговыми сценариями находится в **[Сетевая Изоляция и NetworkPolicy](../Networking/Network/network_policy.md)**.

## Определения

**NetworkPolicy** — объект Kubernetes API для декларативного управления сетевым доступом на уровне L3/L4 между Pod'ами и внешними адресами.

**Селектор Pod'ов (`podSelector`)** — механизм выбора целевых Pod'ов по меткам для применения политик.

**Ingress** — правила входящего трафика к Pod'ам.

**Egress** — правила исходящего трафика от Pod'ов.

**CNI (Container Network Interface)** — плагин сетевой подсистемы Kubernetes, обеспечивающий реализацию NetworkPolicy.

## Основные концепции

### Принцип работы

NetworkPolicy действует по принципу **явного разрешения**:

- По умолчанию (если нет политик, селектящих Pod) — весь трафик разрешён
- При наличии политики с указанным направлением — только явно разрешённый трафик
- Политики **аддитивны**: объединение всех правил из всех селектящих политик
- Пустые списки правил = полный запрет (deny all) по данному направлению

### Требования к CNI

NetworkPolicy работает только при условии поддержки со стороны CNI-плагина:

- ✅ Calico, Cilium, Weave Net
- ❌ Flannel (не поддерживает)

Подробно о ролях CNI: [Роли CNI и kube-proxy](../Networking/Network/cni_kube_proxy_roles.md).

## Практические сценарии

### Сценарий 1: Default Deny (полная изоляция)

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: backend-default-deny
  namespace: team-a
spec:
  podSelector:
    matchLabels:
      app: backend
  policyTypes:
  - Ingress
  - Egress
```

### Сценарий 2: Разрешение конкретного трафика

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: backend-allow-specific
  namespace: team-a
spec:
  podSelector:
    matchLabels:
      app: backend
  policyTypes:
  - Ingress
  - Egress
  ingress:
  - from:
    - podSelector:
        matchLabels:
          app: frontend
    ports:
    - port: 5432
      protocol: TCP
```

## Дополнительная информация

### Ограничения NetworkPolicy

- **L3/L4 только**: нет фильтрации по FQDN/доменам
- **IP-based**: доменные имена учитываются только через разрешённые IP
- **Не отменяет Service**: политики работают на сетевом уровне

### Альтернативы для L7

Для фильтрации по доменам (FQDN) используйте:

- **Cilium** — встроенная поддержка DNS/FQDN
- **Calico** — NetworkSets с доменами
- **Service Mesh** (Istio, Linkerd) — L7-авторизация

### Связанные темы

- **NetworkPolicy:** [Сетевая Изоляция и NetworkPolicy](../Networking/Network/network_policy.md) (полное руководство)
- **Calico HostEndpoint:** [Calico HostEndpoint и GlobalNetworkPolicy](./network_policies/Calico/index.md)
- **CNI и kube-proxy:** [Роли CNI и kube-proxy](../Networking/Network/cni_kube_proxy_roles.md)
- **Сетевая модель:** [Обзор сети Kubernetes](../Networking/Network/network_overview.md)
- **Kyverno:** [Генерация NetworkPolicy](./kyverno.md)
