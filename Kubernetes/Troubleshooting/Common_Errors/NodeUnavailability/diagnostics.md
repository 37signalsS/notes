# Node Unavailability: Diagnostics

## Definitions

**Node Diagnostics** — пошаговый процесс определения причины недоступности узла, начиная от проверки статуса через `kubectl` до анализа системных логов на самом узле.

**Цель:** Быстро локализовать проблему (сеть, kubelet, ресурсы, runtime) и выбрать путь решения.

## Basic Concepts

### Diagnostic Tools

| Инструмент | Назначение | Что показывает |
|-----------|-----------|----------------|
| `kubectl get nodes` | Быстрая проверка | Общий статус всех узлов |
| `kubectl describe node` | Детальный анализ | Conditions, events, taints, allocated resources |
| `journalctl -u kubelet` | Логи kubelet | Ошибки подключения к API server, проблемы с runtime |
| `systemctl status kubelet` | Статус службы | Работает ли kubelet |
| `ss -tlnp` / `netstat` | Проверка портов | Слушает ли kubelet (10250), containerd |

### Node Conditions Diagnostic Output

При `kubectl describe node` обратите внимание на секцию `Conditions`:

```
Conditions:
  Type             Status  LastHeartbeatTime          Reason                       Message
  ----             ------  -----------------          ------                       -------
  MemoryPressure   False   Thu, 05 Mar 2026 ...       KubeletHasSufficientMemory   kubelet has sufficient memory available
  DiskPressure     False   Thu, 05 Mar 2026 ...       KubeletHasNoDiskPressure     kubelet has no disk pressure
  Ready            True    Thu, 05 Mar 2026 ...       KubeletReady                 kubelet is posting ready status
```

**Ключевые маркеры:**

| Reason | Значение |
|--------|----------|
| `KubeletReady` | Kubelet работает и связан с API server |
| `KubeletNotReady` | Kubelet работает, но не готов принимать поды |
| `KubeletStopped` | Kubelet остановлен |
| `NodeStatusNeverUpdated` | API server никогда не получил heartbeat |

### Key Ports

| Порт | Протокол | Назначение |
|------|----------|------------|
| `10250` | TCP | Kubelet API (healthz, logs, exec) |
| `6443` | TCP | API server (kubelet → control plane) |

## Practical Scenarios

### Step-by-Step Diagnostic Checklist

#### Шаг 1: Проверка статуса узлов

```bash
# Быстрая проверка
kubectl get nodes

# Детальная информация
kubectl describe node <node-name>

# Проверка conditions
kubectl get nodes -o custom-columns=NAME:.metadata.name,READY:.status.conditions[?(@.type=="Ready")].status,STATUS:.status.conditions[?(@.type=="Ready")].reason
```

#### Шаг 2: Проверка kubelet на узле

```bash
# SSH на узел
ssh <node-name>

# Статус kubelet
systemctl status kubelet

# Логи kubelet
journalctl -u kubelet -f --no-pager

# Проверка портов
ss -tlnp | grep -E '10250|6443'
```

#### Шаг 3: Проверка системных ресурсов

```bash
# CPU и память
top
free -h

# Дисковое пространство
df -h
df -i  # inodes

# Нагрузка на систему
uptime
```

#### Шаг 4: Проверка сети

```bash
# Проверка связи с control plane
ping <control-plane-ip>

# Проверка порта API server
curl -k https://<control-plane-ip>:6443/healthz

# Проверка DNS
nslookup kubernetes.default

# Проверка CNI
kubectl get pods -n kube-system | grep -E 'calico|flannel|weave'
```

#### Шаг 5: Проверка событий узла

```bash
# События проблемного узла
kubectl get events --field-selector involvedObject.kind=Node,involvedObject.name=<node-name> --sort-by='.lastTimestamp'

# Все события узла
kubectl get events --field-selector involvedObject.kind=Node --sort-by='.lastTimestamp'
```

### Symptom → Root Cause Mapping

| Симптом | Вероятная причина | Следующий шаг |
|---------|-------------------|---------------|
| `Ready=False`, kubelet работает | Resource pressure, CNI | [resource_pressure.md](./resource_pressure.md) |
| `Ready=Unknown`, kubelet не отвечает | Сеть, kubelet упал | [network_issues.md](./network_issues.md), [kubelet_issues.md](./kubelet_issues.md) |
| `Ready=False`, runtime ошибка | Containerd/docker проблема | [runtime_issues.md](./runtime_issues.md) |
| Узел в `SchedulingDisabled` | Плановое обслуживание | [maintenance.md](./maintenance.md) |

## Additional Information

### Definitions and Concepts

Определения NodeNotReady/Unreachable: [definitions.md](./definitions.md).

### Specialized Diagnostic Paths

- Проблемы с kubelet: [kubelet_issues.md](./kubelet_issues.md)
- Проблемы с сетью: [network_issues.md](./network_issues.md)
- Нехватка ресурсов: [resource_pressure.md](./resource_pressure.md)
- Проблемы с runtime: [runtime_issues.md](./runtime_issues.md)
- Taints и eviction: [taints_and_eviction.md](./taints_and_eviction.md)

### Maintenance Procedures

Плановое обслуживание и best practices: [maintenance.md](./maintenance.md).
