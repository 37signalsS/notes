# NetworkPolicy: управление трафиком между Pod'ами

## Определения

**NetworkPolicy** — объект Kubernetes API для декларативного управления сетевым доступом на уровне L3/L4 между Pod'ами и внешними адресами.

**Селектор Pod'ов (`podSelector`)** — механизм выбора целевых Pod'ов по меткам для применения политик.

**Ingress** — правила входящего трафика к Pod'ам.

**Egress** — правила исходящего трафика от Pod'ов.

**CNI (Container Network Interface)** — плагин сетевой подсистемы Kubernetes, обеспечивающий реализацию NetworkPolicy.

## Основные концепции

> **Примечание:** Здесь приведены ключевые моменты. Подробное руководство с пошаговыми сценариями см. в [Сетевая Изоляция и NetworkPolicy](../Networking/Network/network_policy.md).

### Принцип работы

NetworkPolicy действует по принципу **явного разрешения**:

- По умолчанию (если нет политик, селектящих Pod) — весь трафик разрешён
- При наличии политики с указанным направлением — только явно разрешённый трафик
- Политики **аддитивны**: объединение всех правил из всех селектящих политик
- Пустые списки правил = полный запрет (deny all) по данному направлению

### Ключевые элементы спецификации

| Поле | Описание | Пример |
|------|----------|--------|
| `podSelector` | Выбор Pod'ов по меткам | `matchLabels: {app: backend}` |
| `policyTypes` | Направления контроля | `Ingress`, `Egress` |
| `ingress` | Правила входящего трафика | `from`, `ports` |
| `egress` | Правила исходящего трафика | `to`, `ports` |

### Типы источников/получателей (`from`/`to`)

| Тип | Описание | Use Case |
|-----|----------|----------|
| `podSelector` | Pod'ы по меткам в том же namespace | Frontend → Backend |
| `namespaceSelector` | Все Pod'ы в совпавших namespace | Межкомандные интеграции |
| `podSelector` + `namespaceSelector` | Pod'ы в конкретных namespace | Изоляция окружений |
| `ipBlock` | CIDR-диапазоны | Доступ к внешним БД, интернету |

### Требования к CNI

NetworkPolicy работает только при условии поддержки со стороны CNI-плагина:

- Calico, Cilium, Weave Net
- ❌ Flannel (не поддерживает)

Подробно о ролях CNI: [Роли CNI и kube-proxy](../Networking/Network/cni_kube_proxy_roles.md).

## Практические сценарии

> **Примечание:** Ниже приведены краткие примеры. Подробные пошаговые сценарии с объяснениями см. в [Сетевая Изоляция и NetworkPolicy](../Networking/Network/network_policy.md#практический-сценарий-от-изоляции-до-разрешения-dns).

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
  egress:
  - to:
    - ipBlock:
        cidr: 0.0.0.0/0
    ports:
    - port: 443
      protocol: TCP
```

### Сценарий 3: Доступ к внешним сервисам

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: db-access
  namespace: production
spec:
  podSelector:
    matchLabels:
      app: backend
  policyTypes:
  - Egress
  egress:
  - to:
    - ipBlock:
        cidr: 10.0.2.0/24
    ports:
    - port: 5432
      protocol: TCP
```

## Защита узлов с помощью Calico HostEndpoint

Calico расширяет стандартные NetworkPolicy через ресурсы `HostEndpoint` и `GlobalNetworkPolicy`, позволяя создавать периметральный файрвол на уровне узлов.

**Подробная документация:** [Calico HostEndpoint и GlobalNetworkPolicy](./network_policies/calico.md)

## Дополнительная информация

### Ограничения NetworkPolicy

- **L3/L4 только**: нет фильтрации по FQDN/доменам
- **IP-based**: доменные имена учитываются только через разрешённые IP
- **Не отменяет Service**: политики работают на сетевом уровне
- **Матчинг по IP**: при изменении IP Pod'а политика может нарушиться

### Альтернативы для L7

Для фильтрации по доменам (FQDN) используйте:

- **Cilium** — встроенная поддержка DNS/FQDN
- **Calico** — NetworkSets с доменами
- **Service Mesh** (Istio, Linkerd) — L7-авторизация

### Паттерны безопасности

- **Zero Trust**: default deny + явные разрешения
- **Segmentation**: изоляция namespace по командам/окружениям
- **Least Privilege**: минимально необходимые порты и протоколы

### Связанные темы

- **SSoT по NetworkPolicy:** [Сетевая Изоляция и NetworkPolicy](../Networking/Network/network_policy.md)
- **Calico HostEndpoint:** [Calico HostEndpoint и GlobalNetworkPolicy](./network_policies/calico.md)
- **CNI и kube-proxy:** [Роли CNI и kube-proxy](../Networking/Network/cni_kube_proxy_roles.md)
- **Сетевая модель:** [Обзор сети Kubernetes](../Networking/Network/network_overview.md)
- **Sealed Secrets:** [Sealed Secrets](sealed_secrets_overview.md)
- **RBAC:** [RBAC Overview](./rbac/rbac_overview.md)
- **Kubernetes Documentation:** [NetworkPolicy](https://kubernetes.io/docs/concepts/services-networking/network-policies/)
