# Node Unavailability: Kubelet Issues

## Definitions

**Kubelet Issue** — ситуация, при которой агент kubelet на узле не может нормально функционировать (упал, не отвечает, не может подключиться к API server), что приводит к статусу узла `NotReady` или `Unknown`.

**Kubelet** — основной агент на каждом узле, регистрирующий узел в API server и управляющий подами. Подробнее: [kubelet.md](../../../Concepts/kubelet.md).

## Basic Concepts

### Kubelet Architecture (кратко)

| Компонент | Назначение |
|-----------|-----------|
| **API Server Client** | Подключение к control plane, получение PodSpec |
| **Container Runtime Interface (CRI)** | Взаимодействие с containerd/CRI-O |
| **Health Checks** | Liveness/readiness probes для подов |
| **Node Status Reporter** | Отправка conditions (Ready, MemoryPressure, DiskPressure) |
| **Certificate Manager** | Управление TLS-сертификатами kubelet |

### Common Failure Modes

| Тип сбоя | Статус узла | Типичная причина |
|----------|-------------|------------------|
| Kubelet остановлен | `NotReady` / `Unknown` | Crash, OOM kill, systemctl stop |
| Ошибка конфигурации | `NotReady` | Некорректный `config.yaml` |
| Сертификаты истекли | `NotReady` | Истёк `kubelet-client-current.pem` |
| CRI недоступен | `NotReady` | containerd/CRI-O упал |

### Kubelet Configuration

| Параметр | Файл | Описание |
|----------|------|----------|
| Config | `/var/lib/kubelet/config.yaml` | Основная конфигурация |
| Flags | `/etc/sysconfig/kubelet` или `/etc/default/kubelet` | Дополнительные флаги запуска |
| Certs | `/var/lib/kubelet/pki/` | TLS-сертификаты |
| Logs | `journalctl -u kubelet` | Системный журнал |

## Practical Scenarios

### Scenario 1: Kubelet остановлен или не отвечает

**Симптомы:**

- Статус узла: `NotReady` или `Unknown`
- `systemctl status kubelet` → `inactive` или `failed`

**Диагностика:**

```bash
# Статус службы
systemctl status kubelet

# Логи kubelet
journalctl -u kubelet -n 100 --no-pager

# Проверка конфигурации
cat /var/lib/kubelet/config.yaml
```

**Решение:**

```bash
# Перезапуск kubelet
sudo systemctl restart kubelet

# После перезапуска проверить статус узла
kubectl get nodes
```

**Типичные причины в логах:**

| Сообщение | Причина |
|-----------|---------|
| `failed to run Kubelet` | Ошибка конфигурации |
| `unable to register node` | Проблема с авторизацией |
| `container runtime is down` | CRI (containerd) недоступен |

### Scenario 2: Проблемы с сертификатами kubelet

**Симптомы:**

- Kubelet не подключается к API server
- В логах: `x509: certificate has expired` или `TLS handshake timeout`

**Диагностика:**

```bash
# Проверка срока действия сертификата
openssl x509 -in /var/lib/kubelet/pki/kubelet.crt -text -noout | grep -A 2 "Validity"

# Проверка сроков всех сертификатов (kubeadm)
kubeadm certs check-expiration
```

**Решение:**

> ⚠️ Детальное управление сертификатами: [certificate_management.md](../../../Operations/certificate_management.md).

```bash
# Обновление сертификатов через kubeadm
sudo kubeadm certs renew all
sudo systemctl restart kubelet
```

### Scenario 3: Kubelet не регистрирует узел

**Симптомы:**

- Kubelet работает (`systemctl status kubelet` → `active`)
- Узел не появляется в `kubectl get nodes`

**Диагностика:**

```bash
# Проверка авторизации
journalctl -u kubelet | grep -i "forbidden\|unauthorized"

# Проверка bootstrap kubeconfig
ls -la /var/lib/kubelet/bootstrap-kubeconfig

# Проверка токена
kubectl -n kube-system get secrets | grep bootstrap
```

## Additional Information

### Related Concepts

- Kubelet overview: [kubelet.md](../../../Concepts/kubelet.md)
- Certificate management: [certificate_management.md](../../../Operations/certificate_management.md)
- Node diagnostics entry point: [diagnostics.md](./diagnostics.md)

### Related Node Unavailability Paths

- Resource pressure: [resource_pressure.md](./resource_pressure.md)
- Container runtime issues: [runtime_issues.md](./runtime_issues.md)
- Network issues: [network_issues.md](./network_issues.md)
- Node maintenance: [maintenance.md](./maintenance.md)
