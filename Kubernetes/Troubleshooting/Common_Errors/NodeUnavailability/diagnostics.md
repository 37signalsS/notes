# Node Unavailability: Диагностика

## Диагностика: пошаговый чек-лист

### Шаг 1: Проверка статуса узлов

```bash
# Быстрая проверка
kubectl get nodes

# Детальная информация
kubectl describe node <node-name>

# Проверка conditions
kubectl get nodes -o custom-columns=NAME:.metadata.name,READY:.status.conditions[?(@.type=="Ready")].status,STATUS:.status.conditions[?(@.type=="Ready")].reason
```

**Ищите в выводе `kubectl describe`:**

```
Conditions:
  Type             Status  LastHeartbeatTime          Reason                       Message
  ----             ------  -----------------          ------                       -------
  MemoryPressure   False   Thu, 05 Mar 2026 ...       KubeletHasSufficientMemory   kubelet has sufficient memory available
  DiskPressure     False   Thu, 05 Mar 2026 ...       KubeletHasNoDiskPressure     kubelet has no disk pressure
  Ready            True    Thu, 05 Mar 2026 ...       KubeletReady                 kubelet is posting ready status
```

### Шаг 2: Проверка kubelet на узле

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

### Шаг 3: Проверка системных ресурсов

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

### Шаг 4: Проверка сети

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

### Шаг 5: Проверка событий узла

```bash
# События проблемного узла
kubectl get events --field-selector involvedObject.kind=Node,involvedObject.name=<node-name> --sort-by='.lastTimestamp'

# Все события узла
kubectl get events --field-selector involvedObject.kind=Node --sort-by='.lastTimestamp'
```
