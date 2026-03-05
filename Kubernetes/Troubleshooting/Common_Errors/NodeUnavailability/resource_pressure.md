# Node Unavailability: Нехватка ресурсов

## 2. Нехватка ресурсов (Memory/Disk/PID Pressure)

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

### Решения по типам проблем

| Проблема | Решение |
|----------|---------|
| **Memory Pressure** | Очистить кэш, удалить лишние поды, добавить RAM |
| **Disk Pressure** | Очистить логи, удалить старые образы (`crictl rmi --prune`) |
| **PID Pressure** | Увеличить `kernel.pid_max`, уменьшить количество подов на узел |

### Очистка диска

```bash
# Удаление остановленных контейнеров
crictl rm $(crictl ps -a -q --state exited)

# Удаление неиспользуемых образов
crictl rmi --prune

# Очистка логов
journalctl --vacuum-time=1d
```
