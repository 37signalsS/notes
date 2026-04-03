# Node Unavailability: Runtime Issues

## Definitions

**Container Runtime** — низкоуровневое ПО, ответственное за запуск и управление контейнерами на узле. Kubernetes взаимодействует с ним через **CRI** (Container Runtime Interface).

**CRI Failure** — ситуация, при которой kubelet не может подключиться к runtime (containerd, CRI-O), что приводит к невозможности запускать/управлять подами и статусу узла `NotReady`.

## Basic Concepts

### Supported Runtimes

| Runtime | Статус | Примечание |
|---------|--------|------------|
| **containerd** | Default (с K8s 1.24+) | Стандарт de facto после dockershim removal |
| **CRI-O** | Supported | Легковесная альтернатива, focus on Kubernetes |
| **Docker Engine** | Deprecated (через dockershim) | Удалён из K8s 1.24+ |

### Runtime ↔ Kubelet Interaction

| Компонент | Socket | Назначение |
|-----------|--------|-----------|
| containerd | `/run/containerd/containerd.sock` | CRI API для kubelet |
| CRI-O | `/run/crio/crio.sock` | CRI API для kubelet |
| crictl | — | CLI для диагностики CRI runtime |

### Common Runtime Failure Modes

| Сбой | Причина | Симптом |
|------|---------|---------|
| Runtime упал | Crash, OOM | `failed to connect to containerd` |
| Некорректная конфигурация | Ошибка в `config.toml` | Runtime не запускается |
| Истёк сертификат | TLS для private registry | `x509: certificate has expired` |
| Sandbox image недоступен | Нет интернета / mirror down | Поды в `ContainerCreating` |

### Diagnostic Commands

| Команда | Назначение |
|---------|-----------|
| `systemctl status containerd` | Статус службы containerd |
| `crictl info` | Информация о runtime |
| `crictl ps` | Список контейнеров через CRI |
| `crictl pods` | Список sandbox-подов |
| `journalctl -u containerd -f` | Логи containerd |

## Practical Scenarios

### Scenario 1: containerd упал или не отвечает

**Симптомы:**

- Kubelet не может запустить контейнеры
- В логах kubelet: `failed to connect to containerd`
- `kubectl get nodes` → `NotReady`

**Диагностика:**

```bash
# Статус containerd
systemctl status containerd

# Логи containerd
journalctl -u containerd -n 100 --no-pager

# Проверка socket
ls -la /run/containerd/containerd.sock

# Проверка через crictl
crictl info
crictl ps
```

**Решение:**

```bash
# Перезапуск containerd
sudo systemctl restart containerd

# Проверка после restart
crictl info
kubectl get nodes
```

### Scenario 2: Ошибка конфигурации containerd

**Симптомы:**

- containerd не запускается (`systemctl status containerd` → `failed`)
- В логах: ошибка парсинга `config.toml`

**Диагностика:**

```bash
# Проверка конфигурации
cat /etc/containerd/config.toml

# Валидация (containerd 1.6+)
containerd config dump | head -50
```

**Решение:**

```bash
# Восстановление дефолтной конфигурации
sudo cp /etc/containerd/config.toml /etc/containerd/config.toml.bak
sudo containerd config default | sudo tee /etc/containerd/config.toml

# Убедиться в настройках
# SystemdCgroup = true (обязательно для K8s)
# sandbox_image = "registry.k8s.io/pause:3.x"

sudo systemctl restart containerd
```

### Scenario 3: Проблемы с sandbox/pause контейнерами

**Симптомы:**

- Поды зависают в `ContainerCreating`
- В событиях: `Failed to create sandbox`

**Диагностика:**

```bash
# Проверка sandbox-образов
crictl images | grep pause

# Проверка конфигурации sandbox image
containerd config dump | grep sandbox_image
```

**Решение:**

```bash
# Очистка stale sandbox контейнеров
crictl rmp -fa

# Pull актуального sandbox image
crictl pull registry.k8s.io/pause:3.9

# Перезапуск
sudo systemctl restart containerd
```

## Additional Information

### Related Node Unavailability Paths

- Definitions: [definitions.md](./definitions.md)
- Diagnostics checklist: [diagnostics.md](./diagnostics.md)
- Kubelet issues (CRI dependency): [kubelet_issues.md](./kubelet_issues.md)
- Resource pressure (disk cleanup): [resource_pressure.md](./resource_pressure.md)

### External References

- [containerd Documentation](https://github.com/containerd/containerd/blob/main/docs/getting-started.md)
- [CRI-O Documentation](https://cri-o.io/)
- [Dockershim Removal (K8s 1.24)](https://kubernetes.io/blog/2022/02/17/dockershim-faq/)
