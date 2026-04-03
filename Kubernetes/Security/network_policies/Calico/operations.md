# Calico Operations: Troubleshooting и Обслуживание

> Основная документация: [Calico HostEndpoint и GlobalNetworkPolicy](./index.md)

## Definitions

**Calico Operations** — процедуры проверки состояния, отладки и устранения проблем при использовании HostEndpoint и GlobalNetworkPolicy.

---

## Basic Concepts

### Инструменты диагностики

**calicoctl** — CLI-утилита для управления ресурсами Calico (HostEndpoint, GlobalNetworkPolicy, FelixConfiguration). Требует доступ к Kubernetes API.

**Felix status** — статус агента Felix на узле, проверяется через `calicoctl node status`. Показывает состояние BGP-пиров, применённых политик и маршрутов.

---

## Practical Scenarios

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

### NodePort фильтрация

Трафик на `NodePort` может обходить политики из-за особенностей реализации в `iptables` и порядка применения правил до/после DNAT.

**Решение:**

- Использовать `preDNAT: true` + явные правила для портов NodePort
- Рассмотреть `LoadBalancer` вместо `NodePort`
- Использовать `eBPF` режим Calico (более предсказуемое поведение)

### Изменение IP узлов

При изменении IP узла требуется обновить `expectedIPs` в `HostEndpoint`:

```bash
calicoctl get hostendpoint <name> -o yaml | \
  sed 's/old-ip/new-ip/' | \
  calicoctl apply -f -
```

### eBPF режим

Calico поддерживает режим `eBPF` для замены `iptables`. Преимущества: выше производительность, предсказуемое поведение с NodePort, встроенная замена `kube-proxy`.

**Включение:**

```yaml
# В calico-config ConfigMap
- name: FELIX_BPFENABLED
  value: "true"
```

> **Подробнее:** [eBPF в Calico](../../../Networking/Network/CNI/ebpf.md)

### Совместимость версий

| Calico | Kubernetes | Статус |
|--------|------------|--------|
| v3.28.x | 1.28–1.31 | ⚠️ Проверить |
| v3.31.x | 1.28–1.32 | ✅ Рекомендуется |

Всегда проверяйте [официальную матрицу совместимости](https://docs.tigera.io/calico/latest/about/supported-releases).

---

## Additional Information

Связанные ресурсы: [Calico HostEndpoint и GlobalNetworkPolicy](./index.md), [Сценарии Calico](./scenarios.md), [NetworkPolicy](../../network_policies.md), [Сетевая модель](../../../Networking/Network/network_overview.md), [eBPF в Calico](../../../Networking/Network/CNI/ebpf.md).
