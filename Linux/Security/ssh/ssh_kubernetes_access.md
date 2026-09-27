# SSH-доступ к Kubernetes: узлы, поды и контейнеры

## Определения

**Bastion Host (Jump Host)** — сервер с ограниченным доступом, выступающий промежуточным звеном для SSH-подключений к внутренним узлам кластера. Располагается в DMZ или публичной подсети.

**SSH ProxyJump** — механизм SSH для маршрутизации подключения через промежуточный хост. Реализуется через флаг `-J` или опцию `ProxyJump` в `~/.ssh/config`.

**kubectl debug node/** — альтернатива SSH для диагностики узлов через Kubernetes API. Использует эфемерные контейнеры для доступа к хосту.

**Kubelet SSH** — SSH-сервер в контейнере для доступа к ресурсам узла. Используется для отладки и разработки в кластере.

**NodePort** — тип Service в Kubernetes, выделяющий статичный порт на каждом узле кластера (диапазон 30000-32767). Используется для доступа к SSH-серверу в контейнере.

## Базовые концепции

### Архитектура SSH-доступа к Kubernetes

```
Инженер → Bastion (public) → Worker Node (private) → kubelet/containerd
    │            │                      │
    │ SSH ProxyJump│                      │
    └────────────┘                      │
                                        │
    kubectl debug node/ ────────────────┘
    (через API-сервер)
```

### Типичные ограничения доступа

| Сценарий | Прямой SSH | Через bastion | kubectl debug |
| :--- | :--- | :--- | :--- |
| Узел в приватной сети | Невозможен | Через bastion | Возможно |
| Файрвол блокирует 22 | Невозможен | Через bastion | Возможно |
| kubelet упал | SSH работает | SSH работает | Невозможен |
| API-сервер недоступен | SSH работает | SSH работает | Невозможен |
| Узел полностью мёртв | Невозможен | Невозможен | Невозможен |

## Практические сценарии

### Сценарий 1: SSH ProxyJump через bastion

**Задача**: Настроить безопасный доступ к узлам в приватной сети через bastion.

```bash
# ~/.ssh/config

# Bastion host
Host bastion
    HostName bastion.example.com
    User admin
    Port 22
    IdentityFile ~/.ssh/bastion_key

# Worker nodes через bastion
Host node-1 node-2 node-3
    ProxyJump bastion
    User admin
    IdentityFile ~/.ssh/worker_key
    StrictHostKeyChecking accept-new

# Группа узлов через bastion
Host 10.0.1.*
    ProxyJump bastion
    User admin
    IdentityFile ~/.ssh/worker_key
    StrictHostKeyChecking accept-new
```

**Подключение:**
```bash
# Простое подключение через bastion
ssh admin@node-1

# С портом и ключом
ssh -i ~/.ssh/worker_key -p 22 admin@node-1

# Команда на удалённом узле
ssh admin@node-1 "sudo systemctl status kubelet"
```

### Сценарий 2: SSH tunnel для доступа к kubelet API

**Задача**: Проброс порта kubelet (10250) через bastion для доступа к метрикам и exec.

```bash
# Проброс 10250 порта через bastion на локальный 10250
ssh -L 10250:node-1:10250 admin@bastion

# Теперь kubelet доступен локально
curl -sk https://127.0.0.1:10250/healthz
# → ok

# Получение метрик
curl -sk https://127.0.0.1:10250/metrics | head -20

# Проброс нескольких портов
ssh -L 10250:node-1:10250 \
    -L 6443:api-server:6443 \
    -L 2379:etcd:2379 \
    admin@bastion
```

### Сценарий 3: Диагностика через kubectl debug (без SSH)

**Задача**: Диагностика узла, когда SSH недоступен, но API-сервер работает.

```bash
# 1. Запуск отладочного контейнера на проблемном узле
kubectl debug node/node-1 -it --image=ubuntu:24.04 --profile=sysadmin

# 2. Внутри контейнера — chroot в хост
chroot /host

# 3. Проверка системных служб
systemctl status kubelet containerd

# 4. Проверка логов kubelet
journalctl -u kubelet -n 50 --no-pager

# 5. Проверка ресурсов
free -h
df -h
ps aux | head -20
```

### Сценарий 4: SSH в контейнерах Kubernetes

**Задача**: Настройка SSH-сервера в Pod для удаленной разработки.

```yaml
# dev-container.yaml
apiVersion: v1
kind: Pod
metadata:
  name: dev-container
  namespace: development
spec:
  containers:
  - name: dev-ssh
    image: ubuntu:24.04
    ports:
    - containerPort: 22
      name: ssh
    volumeMounts:
    - name: home
      mountPath: /home/dev
    securityContext:
      runAsUser: 1000
      runAsNonRoot: true
  volumes:
  - name: home
    persistentVolumeClaim:
      claimName: dev-home-pvc
---
apiVersion: v1
kind: Service
metadata:
  name: dev-ssh
  namespace: development
spec:
  type: NodePort
  selector:
    app: dev-ssh
  ports:
  - port: 22
    targetPort: 22
    nodePort: 30022
```

**Подключение:**
```bash
# Через NodePort
ssh dev@<node-ip> -p 30022

# Через kubectl port-forward
kubectl port-forward pod/dev-container 2222:22 -n development
ssh dev@localhost -p 2222
```

## Дополнительная информация

### Метрики доступности для мониторинга

| Метрика | Описание | Типичный порог алерта |
| :--- | :--- | :--- |
| `probe_success` | SSH-доступ к узлу (blackbox exporter) | == 0持续 5 минут |
| `probe_duration_seconds` | Время SSH-подключения | > 5持续 |
| `kube_node_status_condition{condition="Ready"}` | Готовность узла | == 0持续 2 минуты |

### Полезные команды

```bash
# SSH ProxyJump
ssh -J user@bastion user@target
ssh -J user@bastion1,user@bastion2 user@target

# SSH tunnel
ssh -L local_port:target:target_port user@bastion
ssh -L 6443:api-server:6443 admin@bastion
ssh -L 10250:node-1:10250 admin@bastion

# kubectl port-forward
kubectl port-forward svc/monitoring-grafana 3000:3000
kubectl port-forward pod/etcd-cp1 2379:2379 -n kube-system
```

### См. также

- [Недоступность узла: SSH-доступ и bastion-хосты](../../Kubernetes/Troubleshooting/Common_Errors/NodeUnavailability/bastion_ssh_access.md) — детальная диагностика
- [Создание Dev-контейнера с SSH](../../Kubernetes/Installation/k3s_dev_environment/dev_container_ssh.md) — SSH в K3s
- [Безопасность Kubelet](../../Kubernetes/Security/kubelet_security.md) — Kubelet API security
- [SSH Client Config](./ssh_client_config.md) — настройка SSH-клиента
- [SSH Usage and Tunnels](./ssh_usage_and_tunnels.md) — порты и туннели
- [Инструменты сетевого мониторинга](../Tools/network_monitoring_tools.md) — tcpdump, tshark, ss для анализа SSH-трафика
