# Pod Evicted: Нехватка диска

## 2. Eviction из-за нехватки диска (`DiskPressure`)

**Сообщение:**

```
The node was low on resource: ephemeral-storage.
```

**Причина:** Нехватка места на диске для ephemeral-данных (логи, temporary files, emptyDir).

**Диагностика:**

```bash
# Проверка дискового пространства
df -h /var/lib/kubelet

# Поиск больших файлов
du -ah /var/lib/kubelet | sort -rh | head -20

# Проверка логов контейнеров
du -sh /var/log/containers/*
```

**Решение:**

| Вариант | Описание |
|---------|----------|
| **Очистка логов** | Настроить log rotation |
| **Очистка образов** | `crictl rmi --prune` или `docker image prune` |
| **Увеличение диска** | Расширить volume узла |
| **Настройка limits** | `ephemeral-storage` limits для подов |

**Настройка limits для ephemeral-storage:**

```yaml
resources:
  requests:
    ephemeral-storage: "1Gi"
  limits:
    ephemeral-storage: "5Gi"
```

**Настройка log rotation для containerd:**

```toml
# /etc/containerd/config.toml
[plugins."io.containerd.grpc.v1.cri".containerd.log]
  level = "info"
  max_size = "100Mi"
  max_backups = 5
```
