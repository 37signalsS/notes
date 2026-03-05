# Node Unavailability: Проблемы с Container Runtime

## 6. Проблемы с container runtime

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
