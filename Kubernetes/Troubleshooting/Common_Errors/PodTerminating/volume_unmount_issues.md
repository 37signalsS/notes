# Pod Terminating: Volume Unmount проблемы

## 1. Volume не может размонтироваться

**Сообщение:**

```
Unable to attach or mount volumes: timed out waiting for the condition
volume "data-vol" is still attached to node
```

**Причина:** Процесс все еще использует файлы на томе, или CSI driver не отвечает.

**Диагностика:**

```bash
# SSH на узел
ssh <node-name>

# Получение UID пода
POD_UID=$(kubectl get pod <pod-name> -o jsonpath='{.metadata.uid}')

# Поиск точек монтирования
findmnt | grep $POD_UID

# Поиск процессов, использующих volume
lsof +D /var/lib/kubelet/pods/$POD_UID/volumes
fuser -vm /var/lib/kubelet/pods/$POD_UID
```

**Решение:**

```bash
# Принудительное размонтирование (lazy unmount)
umount -l /var/lib/kubelet/pods/$POD_UID/volumes/*/mount

# Или конкретную точку
umount -l <mount-point>

# Перезапуск kubelet (если не помогает)
systemctl restart kubelet
```

> **Warning:** Lazy unmount (`-l`) может привести к потере данных, если приложение еще пишет в volume.
