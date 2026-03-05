# Проблемы с доступностью узлов (`NodeNotReady` / `Node Unreachable`)

## Определения

**`NodeNotReady`** — статус узла (`Node`), означающий, что `kubelet` на узле работает, но сообщает, что узел не готов принимать новые поды.

**`Node Unreachable`** — состояние, при котором `kube-apiserver` не может связаться с `kubelet` на узле через контрольный канал (health check timeout).

> - Taints: [`taints_and_tolerations.md`](../../Scheduling/taints_and_tolerations.md)
> - Eviction: [`pod_evicted.md](./pod_evicted.md)
> - Обслуживание узлов: [`node_maintenance.md`](../../Operations/node_maintenance.md)
> - High Availability: [`high_availability.md`](../../Base/high_availability.md)
> - Cluster Autoscaler: [`cluster_autoscaler_detailed.md`](../../Autoscaling/cluster_autoscaler_detailed.md)

**Важно:** Это статусы узла, а не пода. Влияют на все поды, размещенные на проблемном узле.

## Основные концепции

### Node Conditions

Kubernetes отслеживает следующие условия узла:

| Condition | Описание | Нормальный статус |
|-----------|----------|-------------------|
| **`Ready`** | Узел готов принимать поды | `True` |
| **`MemoryPressure`** | Нехватка памяти | `False` |
| **`DiskPressure`** | Нехватка диска | `False` |
| **`PIDPressure`** | Исчерпание PID | `False` |
| **`NetworkUnavailable`** | Сеть недоступна | `False` |

### Статусы узлов

| Статус | Condition | Описание |
|--------|-----------|----------|
| **`Ready`** | `Ready=True` | Узел работает нормально |
| **`NotReady`** | `Ready=False` | Kubelet работает, но узел не готов |
| **`Unknown`** | `Ready=Unknown` | Kubelet не отвечает (Unreachable) |
| **`SchedulingDisabled`** | `unschedulable=true` | Узел в cordon (обслуживание) |

### Taints при проблемах с узлом

Kubernetes автоматически добавляет taints при проблемах:

| Taint | Effect | Когда добавляется |
|-------|--------|-------------------|
| `node.kubernetes.io/not-ready:NoExecute` | `NoExecute` | Узел в статусе `NotReady` |
| `node.kubernetes.io/unreachable:NoExecute` | `NoExecute` | Узел в статусе `Unknown` |
| `node.kubernetes.io/memory-pressure:NoSchedule` | `NoSchedule` | Condition `MemoryPressure=True` |
| `node.kubernetes.io/disk-pressure:NoSchedule` | `NoSchedule` | Condition `DiskPressure=True` |
| `node.kubernetes.io/pid-pressure:NoSchedule` | `NoSchedule` | Condition `PIDPressure=True` |
| `node.kubernetes.io/network-unavailable:NoSchedule` | `NoSchedule` | Condition `NetworkUnavailable=True` |

> **См. также:** [`taints_and_tolerations.md`](../../Scheduling/taints_and_tolerations.md)

### Eviction Timeout

При недоступности узла:

```
Узел становится Unreachable
    ↓
node-controller ждет 40 секунд (по умолчанию)
    ↓
Добавляется taint `unreachable:NoExecute`
    ↓
Поды без toleration начинают выселяться
    ↓
Через 5 минут (tolerationSeconds) поды удалены
```

**Параметры:**
- `--pod-eviction-timeout` (по умолчанию 5m0s) — время до начала eviction
- `--node-monitor-grace-period` (по умолчанию 40s) — время до статуса `Unknown`

> **См. также:** [`high_availability.md`](../../Base/high_availability.md)

## Практические сценарии

### Диагностика: пошаговый чек-лист

#### Шаг 1: Проверка статуса узлов

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

### Распространенные случаи и решения

#### 1. Kubelet остановлен или не отвечает

**Симптомы:**
- Статус узла: `NotReady` или `Unknown`
- `systemctl status kubelet` показывает `inactive` или `failed`

**Причины:**
- Сбой процесса kubelet
- Ошибка конфигурации
- Нехватка ресурсов

**Решение:**
```bash
# Перезапуск kubelet
sudo systemctl restart kubelet

# Проверка логов
journalctl -u kubelet -n 100 --no-pager

# Проверка конфигурации
cat /var/lib/kubelet/config.yaml
```

#### 2. Нехватка ресурсов (Memory/Disk/PID Pressure)

**Симптомы:**
- Condition `MemoryPressure=True`, `DiskPressure=True`, или `PIDPressure=True`
- Поды не планируются на узел

**Диагностика:**
```bash
# Проверка памяти
free -h
kubectl top node <node-name>

# Проверка диска
df -h /var/lib/kubelet
du -sh /var/lib/kubelet/pods/*

# Проверка PID
ps aux | wc -l
cat /proc/sys/kernel/pid_max
```

**Решение:**
| Проблема | Решение |
|----------|---------|
| **Memory Pressure** | Очистить кэш, удалить лишние поды, добавить RAM |
| **Disk Pressure** | Очистить логи, удалить старые образы (`crictl rmi --prune`) |
| **PID Pressure** | Увеличить `kernel.pid_max`, уменьшить количество подов на узел |

**Очистка диска:**
```bash
# Удаление остановленных контейнеров
crictl rm $(crictl ps -a -q --state exited)

# Удаление неиспользуемых образов
crictl rmi --prune

# Очистка логов
journalctl --vacuum-time=1d
```

#### 3. Проблемы с сетью (Network Unavailable)

**Симптомы:**
- Condition `NetworkUnavailable=True`
- Поды не получают IP-адреса
- CNI плагин не работает

**Диагностика:**
```bash
# Проверка CNI подов
kubectl get pods -n kube-system -l k8s-app=<cni-plugin>

# Логи CNI
kubectl logs -n kube-system -l k8s-app=<cni-plugin>

# Проверка CNI конфигурации
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

> **См. также:** [`network_policies.md`](../../Security/network_policies.md), [`calico.md`](../../Security/network_policies/calico.md)

#### 4. Узел выключен или недоступен по сети

**Симптомы:**
- Статус узла: `Unknown`
- Нет связи по SSH
- Сервер не отвечает на ping

**Причины:**
- Аппаратный сбой
- Проблемы с питанием
- Сетевая изоляция

**Решение:**
```bash
# Проверка физического сервера (IPMI/iLO)
ipmitool power status

# Принудительное удаление узла (если не вернется)
kubectl delete node <node-name>

# Для StatefulSet подов — пересоздание на другом узле
kubectl delete pod <pod-name> --force --grace-period=0
```

> **Важно:** При удалении узла поды будут пересозданы на других узлах (если есть контроллер).

#### 5. Проблемы с сертификатами kubelet

**Симптомы:**
- Kubelet не может подключиться к API server
- В логах: `x509: certificate has expired`

**Диагностика:**
```bash
# Проверка срока действия сертификата
openssl x509 -in /var/lib/kubelet/pki/kubelet.crt -text -noout | grep -A 2 "Validity"

# Проверка через kubeadm (если используется)
kubeadm certs check-expiration
```

**Решение:**
```bash
# Обновление сертификатов через kubeadm
sudo kubeadm certs renew all
sudo systemctl restart kubelet

# Или пересоздание сертификата kubelet
# См. [`certificate_management.md`](../../Operations/certificate_management.md)
```

#### 6. Проблемы с container runtime

**Симптомы:**
- Kubelet не может запустить контейнеры
- В логах: `failed to connect to containerd`

**Диагностика:**
```bash
# Проверка статуса containerd
systemctl status containerd

# Проверка crictl
crictl info
crictl ps
```

**Решение:**
```bash
# Перезапуск containerd
sudo systemctl restart containerd

# Проверка конфигурации
cat /etc/containerd/config.toml

# Пересоздание sandbox контейнеров
crictl rmp -fa
```

### Обслуживание узлов (Planned Maintenance)

**Стандартная процедура:**

```bash
# 1. Cordon — запрет новых подов
kubectl cordon <node-name>

# 2. Drain — выселение существующих подов
kubectl drain <node-name> \
  --ignore-daemonsets \
  --delete-emptydir-data \
  --force

# 3. Обслуживание узла
# reboot, update kernel, hardware maintenance

# 4. Uncordon — возврат в работу
kubectl uncordon <node-name>
```

> **См. также:** [`node_maintenance.md`](../../Operations/node_maintenance.md)

## Дополнительная информация

### Влияние на поды

| Статус узла | Влияние на поды |
|-------------|-----------------|
| **`NotReady`** | Поды продолжают работать, новые не планируются |
| **`Unknown`** (>40s) | Добавляется taint `unreachable:NoExecute` |
| **`Unknown`** (>5m) | Поды без toleration выселяются |

### Taint tolerations для системных подов

Kubernetes автоматически добавляет tolerations ко всем подам:

```yaml
tolerations:
- key: "node.kubernetes.io/not-ready"
  operator: "Exists"
  effect: "NoExecute"
  tolerationSeconds: 300
- key: "node.kubernetes.io/unreachable"
  operator: "Exists"
  effect: "NoExecute"
  tolerationSeconds: 300
```

### Мониторинг и алерты

```yaml
# Prometheus alerts
- alert: NodeNotReady
  expr: kube_node_status_condition{condition="Ready",status="true"} == 0
  for: 5m
  labels:
    severity: critical

- alert: NodeUnreachable
  expr: absent(kube_node_info) unless absent(kube_node_status_condition)
  for: 10m
  labels:
    severity: warning

- alert: NodeMemoryPressure
  expr: kube_node_status_condition{condition="MemoryPressure",status="true"} == 1
  for: 5m
  labels:
    severity: warning
```

### Best Practices

| Практика | Описание |
|----------|----------|
| **Минимум 3 узла** | Для HA control plane |
| **PodDisruptionBudget** | Защита от массового выселения |
| **Node Autoscaling** | Автоматическая замена неисправных узлов |
| **Мониторинг kubelet** | Алерты на статус и ресурсы |
| **Регулярное обновление** | Патчи безопасности, обновление ядра |

### Ссылки

- [Node Condition](https://kubernetes.io/docs/concepts/architecture/node/#condition)
- [Node Maintenance](https://kubernetes.io/docs/tasks/administer-cluster/safely-drain-node/)
- [Critical Pod Eviction](https://kubernetes.io/docs/concepts/scheduling-eviction/node-pressure-eviction/)
