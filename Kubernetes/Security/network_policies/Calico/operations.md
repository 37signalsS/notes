# Операции Calico: troubleshooting и обслуживание

## Определения

**Операции Calico** — проверка состояния, отладка и устранение проблем при использовании HostEndpoint и GlobalNetworkPolicy.

> **Навигация:** [Главная Calico](./index.md) | [Сценарии](./scenarios.md)

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

---

### Troubleshooting

| Проблема | Возможная причина | Решение |
|----------|-------------------|---------|
| Блокировка SSH после применения | Отсутствует `node-endpoint-type` метка | Добавить метку, применить политику до HostEndpoint |
| NodePort не фильтруется | `preDNAT: false` | Установить `preDNAT: true` |
| BGP не работает | Блокировка порта 179 | Разрешить BGP в политике |
| DNS не работает | Блокировка outbound 53 | Добавить egress правило для DNS |

---

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

---

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

---

### Совместимость версий

| Calico | Kubernetes | Статус |
|--------|------------|--------|
| v3.28.x | 1.28–1.31 | ⚠️ Проверить |
| v3.31.x | 1.28–1.32 | ✅ Рекомендуется |

> **Важно:** Всегда проверяйте [официальную матрицу совместимости](https://docs.tigera.io/calico/latest/about/supported-releases).

---

## Additional Information

### Связанные темы

- **[NetworkPolicy](../network_policies.md)** — стандартные NetworkPolicy
- **[Сетевая модель](../../Networking/Network/network_overview.md)** — обзор сети Kubernetes
- **[Официальная документация](https://docs.tigera.io/calico/latest/)** — документация Calico
