# Node Unavailability: Resource Pressure

## Definitions

**Resource Pressure** — состояние узла, при котором нехватка системных ресурсов (память, диск, PID) приводит к установке conditions `MemoryPressure=True`, `DiskPressure=True` или `PIDPressure=True`. Kubelet перестаёт принимать новые поды и начинает eviction существующих.

**Eviction** — процесс выселения подов с узла kubelet'ом при нехватке ресурсов. Отличается от административного drain ([maintenance.md](./maintenance.md)) — происходит автоматически.

## Basic Concepts

### Pressure Conditions

| Condition | Resource | Trigger | Effect |
|-----------|----------|---------|--------|
| `MemoryPressure=True` | RAM | Использовано > доступного | Новые поды не планируются, eviction |
| `DiskPressure=True` | Disk | Available < eviction threshold | Новые поды не планируются, eviction |
| `PIDPressure=True` | PID | Количество процессов ≈ limit | Новые поды не планируются |

### Eviction Thresholds (kubelet defaults)

| Resource | Soft Threshold | Hard Threshold |
|----------|---------------|----------------|
| **Memory** | `memory.available < 100Mi` | `memory.available < 100Mi` |
| **Disk** | `nodefs.available < 10%` | `nodefs.available < 5%` |
| **ImageFS** | `imagefs.available < 15%` | `imagefs.available < 5%` |
| **PID** | `pid.available < 0` | — |

> **Примечание:** Точные значения зависят от конфигурации kubelet. См. `/var/lib/kubelet/config.yaml`.

### Diagnostic Tools

| Команда | Назначение |
|---------|-----------|
| `free -h` | Общая память (RAM + swap) |
| `kubectl top node <node>` | Использование ресурсов узлом |
| `df -h /var/lib/kubelet` | Свободное место |
| `df -i` | Свободные inodes |
| `ps aux \| wc -l` + `cat /proc/sys/kernel/pid_max` | Использование PID |

## Practical Scenarios

### Scenario 1: MemoryPressure

**Симптомы:**

- Condition `MemoryPressure=True`
- Поды в статусе `Evicted` с сообщением `The node was low on resource: memory`
- OOM killer в системных логах

**Диагностика:**

```bash
# Проверка памяти
free -h
kubectl top node <node-name>

# Кто потребляет память?
ps aux --sort=-%mem | head -20

# OOM killer события
dmesg | grep -i "out of memory" | tail -10
```

**Решение:**

```bash
# Очистка кэша (временная мера)
sync && echo 3 > /proc/sys/vm/drop_caches

# Удаление неиспользуемых образов
crictl rmi --prune

# Долгосрочное: добавить RAM или уменьшить requests/limits
```

### Scenario 2: DiskPressure

**Симптомы:**

- Condition `DiskPressure=True`
- Поды не запускаются: `FailedScheduling` — `Insufficient storage`
- `df -h` показывает >90% usage

**Диагностика:**

```bash
# Дисковое пространство
df -h /var/lib/kubelet

# Кто потребляет место?
du -sh /var/lib/kubelet/pods/* | sort -rh | head -10
du -sh /var/lib/containerd/* | sort -rh | head -10

# Inodes
df -i /var/lib/kubelet
```

**Решение:**

```bash
# Удаление остановленных контейнеров
crictl rm $(crictl ps -a -q --state exited)

# Удаление неиспользуемых образов
crictl rmi --prune

# Очистка логов
journalctl --vacuum-time=1d

# Очистка пустых томов
find /var/lib/kubelet/pods -name "empty-dir" -type d -empty -delete
```

### Scenario 3: PIDPressure

**Симптомы:**

- Condition `PIDPressure=True`
- Невозможно запустить новые процессы на узле
- `fork: retry: Resource temporarily unavailable`

**Диагностика:**

```bash
# Текущее количество процессов
ps aux | wc -l

# Лимит PID
cat /proc/sys/kernel/pid_max

# Кто создаёт процессы?
ps -eo pid,ppid,cmd --sort=-pid | head -20
```

**Решение:**

```bash
# Временное: увеличить лимит
sudo sysctl kernel.pid_max=4194304

# Постоянное: добавить в /etc/sysctl.d/99-pid.conf
echo "kernel.pid_max=4194304" | sudo tee /etc/sysctl.d/99-pid.conf

# Долгосрочное: уменьшить количество подов на узле
# (через --max-pods в kubelet или node capacity)
```

## Additional Information

### Related Node Unavailability Paths

- Definitions: [definitions.md](./definitions.md)
- Diagnostics checklist: [diagnostics.md](./diagnostics.md)
- Taints and eviction: [taints_and_eviction.md](./taints_and_eviction.md)
- Maintenance procedures: [maintenance.md](./maintenance.md)

### External References

- [Node Pressure Eviction](https://kubernetes.io/docs/concepts/scheduling-eviction/node-pressure-eviction/)
- [Kubelet Configuration](https://kubernetes.io/docs/reference/config-api/kubelet-config.v1beta1/)
