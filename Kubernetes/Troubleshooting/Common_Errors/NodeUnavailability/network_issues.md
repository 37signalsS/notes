# Node Unavailability: Network Issues

## Definitions

**NetworkUnavailable** — condition узла (`NetworkUnavailable=True`), означающая, что CNI-плагин не настроил сеть для подов. Новые поды не получают IP-адреса, существующие теряют связность.

**Node Unreachable (Network)** — ситуация, при которой узел полностью недоступен по сети (нет SSH, ping, IPMI). В отличие от проблем kubelet, причина — аппаратная или сетевая.

## Basic Concepts

### Network Failure Types

| Тип сбоя | Condition | Статус узла | Причина |
|----------|-----------|-------------|---------|
| CNI не настроен | `NetworkUnavailable=True` | `NotReady` | Плагин не установлен, ошибка конфигурации |
| Сетевая изоляция | — | `Unknown` | Файрвол, разрыв канала |
| Аппаратный сбой | — | `Unknown` | Питание, железо, гипервизор |

### CNI (Container Network Interface)

| Компонент | Назначение |
|-----------|-----------|
| `/etc/cni/net.d/` | Конфигурация CNI на узле |
| CNI DaemonSet | Поды плагина (Calico, Cilium, Flannel) в `kube-system` |
| kube-proxy | Настройка iptables/ipvs для Service routing |

### CNI Diagnostic Commands

| Команда | Назначение |
|---------|-----------|
| `kubectl get pods -n kube-system -l k8s-app=<cni>` | Проверка подов CNI |
| `kubectl logs -n kube-system -l k8s-app=<cni>` | Логи CNI-плагина |
| `ls -la /etc/cni/net.d/` | Конфигурация CNI на узле |
| `iptables -L -n \| grep -E 'KUBE\|CNI'` | Правила маршрутизации |

## Practical Scenarios

### Scenario 1: CNI не работает (NetworkUnavailable=True)

**Симптомы:**

- Condition `NetworkUnavailable=True`
- Поды не получают IP-адреса (`Pending` или `ContainerCreating`)
- CNI DaemonSet поды в `CrashLoopBackOff` или `Error`

**Диагностика:**

```bash
# Проверка CNI подов
kubectl get pods -n kube-system -l k8s-app=<cni-plugin>

# Логи CNI
kubectl logs -n kube-system -l k8s-app=<cni-plugin>

# Проверка CNI конфигурации на узле
ls -la /etc/cni/net.d/
```

**Решение:**

```bash
# Перезапуск CNI плагина
kubectl rollout restart daemonset -n kube-system <cni-ds-name>

# Проверка правил iptables
iptables -L -n | grep -E 'KUBE|CNI'

# Пересоздание CNI конфигурации
kubectl apply -f <cni-manifest.yaml>
```

### Scenario 2: Узел выключен или недоступен по сети

**Симптомы:**

- Статус узла: `Unknown`
- Нет связи по SSH
- Сервер не отвечает на ping

**Причины:**

- Аппаратный сбой
- Проблемы с питанием
- Сетевая изоляция

**Диагностика:**

```bash
# Проверка физического сервера (IPMI/iLO)
ipmitool power status

# Если VM — проверка гипервизора
virsh list --all          # KVM
Get-VM                    # Hyper-V
```

**Решение:**

```bash
# Если узел не восстановится — принудительное удаление
kubectl delete node <node-name>

# Для StatefulSet подов — принудительное удаление
kubectl delete pod <pod-name> --force --grace-period=0
```

> ⚠️ **Важно:** При удалении узла поды будут пересозданы на других узлах (если есть controller). StatefulSet с `volumeClaimTemplates` требует внимания к PVC.

### Scenario 3: Частичная потеря связности

**Симптомы:**

- Узел периодически `NotReady` → `Ready`
- Поды на узле теряют соединение с API server
- Сетевые таймауты

**Диагностика:**

```bash
# Проверка стабильности сети с узла
ping -c 100 <control-plane-ip> | grep "packet loss"

# Проверка DNS
nslookup kubernetes.default

# Проверка kube-proxy
kubectl get pods -n kube-system -l k8s-app=kube-proxy
kubectl logs -n kube-system -l k8s-app=kube-proxy
```

**Типичные причины:**

| Причина | Диагностика |
|---------|-------------|
| Нестабильный канал | `packet loss > 0` в ping |
| DNS проблемы | `nslookup` fails |
| kube-proxy не работает | Поды kube-proxy в `Error` |

## Additional Information

### Related Node Unavailability Paths

- Diagnostics checklist: [diagnostics.md](./diagnostics.md)
- Definitions: [definitions.md](./definitions.md)
- Taints (network-unavailable): [taints_and_eviction.md](./taints_and_eviction.md)

### External References

- [CNI Specification](https://github.com/containernetworking/cni)
- [Kubernetes Networking](https://kubernetes.io/docs/concepts/cluster-administration/networking/)
