# Недоступность узла: SSH-доступ и bastion-хосты

Диагностика недоступных узлов Kubernetes требует прямого доступа к хосту через SSH. В продакшен-средах прямой SSH часто невозможен из-за файрволов, сетевой сегментации или отсутствия публичных IP. Bastion-хосты (jump hosts) обеспечивают безопасный туннель для доступа к узлам кластера.

## Основные определения

**Bastion Host (Jump Host)** — сервер с ограниченным доступом, выступающий промежуточным звеном для SSH-подключений к внутренним узлам. Располагается в DMZ или публичной подсети, имеет доступ к приватной сети кластера.

**SSH ProxyJump** — механизм SSH для маршрутизации подключения через промежуточный хост. Реализуется через флаг `-J` или опцию `ProxyJump` в `~/.ssh/config`. Пакеты шифруются端到端, bastion не видит трафик.

**SSH Tunnel (Local Port Forwarding)** — проброс локального порта на удалённый хост через bastion. Используется для доступа к API-серверу, kubelet, etcd или другим сервисам, доступным только из приватной сети.

**kubectl debug node/** — альтернатива SSH для диагностики узлов через Kubernetes API. Использует эфемерные контейнеры для доступа к хосту. Не требует SSH, но требует доступа к API-серверу.

## Основные концепции

### Архитектура доступа к узлам

```
Инженер → Bastion (public) → Worker Node (private) → kubelet/containerd
    │            │                      │
    │ SSHProxyJump│                      │
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
| Нет bastion | Невозможен | Невозможен | Возможно |

### Порты для диагностики

| Порт | Сервис | Назначение |
| :--- | :--- | :--- |
| **22** | SSH | Доступ к хосту для диагностики |
| **6443** | kube-apiserver | API-сервер (исходящий от kubelet) |
| **10250** | kubelet API | exec, logs, метрики (входящий) |
| **10248** | kubelet healthz | Проверка здоровья kubelet |
| **2379-2380** | etcd | Client/peer communication |
| **179** | BGP (Calico) | Роутинг подов |
| **4789/UDP** | VXLAN | Overlay-сеть |

## Практические сценарии

### Сценарий 1: SSH ProxyJump через bastion

**Контекст**: Узлы в приватной сети, bastion доступен по публичному IP.

**Настройка SSH config:**
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

# Доступ к нескольким узлам параллельно
for node in node-1 node-2 node-3; do
  ssh admin@$node "hostname; uptime; systemctl is-active kubelet" &
done
wait
```

---

### Сценарий 2: SSH tunnel для доступа к kubelet API

**Контекст**: kubelet API (10250) доступен только из приватной сети. Нужен доступ к метрикам и exec.

**Создание туннеля:**
```bash
# Проброс 10250 порта через bastion на локальный 10250
ssh -L 10250:node-1:10250 admin@bastion

# Теперь kubelet доступен локально
curl -sk https://127.0.0.1:10250/healthz
# → ok

# Получение метрик
curl -sk https://127.0.0.1:10250/metrics | head -20

# Exec в контейнер через kubelet API
# (требуетubectl proxy или прямой curl)
```

**Проброс нескольких портов:**
```bash
# kubelet + API-сервер + etcd
ssh -L 10250:node-1:10250 \
    -L 6443:api-server:6443 \
    -L 2379:etcd:2379 \
    admin@bastion

# Теперь доступны:
# kubelet: https://127.0.0.1:10250
# API: https://127.0.0.1:6443
# etcd: https://127.0.0.1:2379
```

---

### Сценарий 3: Диагностика через kubectl debug (без SSH)

**Контекст**: SSH недоступен, но API-сервер работает.

**Запуск эфемерного контейнера:**
```bash
# 1. Запуск отладочного контейнера на проблемном узле
kubectl debug node/node-1 -it --image=ubuntu:24.04 --profile=sysadmin
# Профиль sysadmin даёт доступ к:
# - Файловой системе хоста в /host
# - Процессам хоста
# - Сети хоста

# 2. Внутри контейнера — chroot в хост
chroot /host

# 3. Проверка системных служб
systemctl status kubelet containerd
# → kubelet.service - kubelet: The Kubernetes Node Agent
# →    Active: active (running)

# 4. Проверка логов kubelet
journalctl -u kubelet -n 50 --no-pager

# 5. Проверка ресурсов
free -h
df -h
ps aux | head -20

# 6. Проверка сети
ip addr
ip route
curl -sk https://127.0.0.1:10250/healthz
```

**Продвинутый debug с nsenter:**
```bash
# Запуск контейнера с hostPID и hostNetwork
kubectl debug node/node-1 -it --image=ubuntu:24.04 \
  --profile=sysadmin \
  --host-path /proc/1/ns/pid \
  --target pid

# Внутри контейнера — доступ к процессам хоста через nsenter
nsenter -t 1 -m -u -i -n -p -- systemctl status kubelet
```

---

### Сценарий 4: Диагностика при недоступном API-сервере

**Контекст**: API-сервер недоступен, kubectl debug невозможно. Только SSH через bastion.

**Алгоритм диагностики:**
```bash
# 1. Подключение к bastion
ssh admin@bastion

# 2. Подключение к проблемному узлу
ssh admin@node-1

# 3. Базовые проверки
# 3.1. Статус сервисов
systemctl status kubelet containerd

# 3.2. Логи kubelet
journalctl -u kubelet -n 100 --no-pager | grep -iE "error|fail|panic"

# 3.3. Логи containerd
journalctl -u containerd -n 50 --no-pager | grep -iE "error|fail"

# 3.4. Сетевая связность с API-сервером
curl -sk https://<api-server>:6443/healthz
# → ok

# 3.5. DNS-резолв
nslookup kubernetes.default.svc.cluster.local

# 3.6. Проверка портов
nc -zv <api-server> 6443
nc -zv localhost 10250

# 3.7. Ресурсы
free -h
df -h
ps aux | grep -E "kubelet|containerd|etcd"

# 3.8. dmesg (ошибки ядра)
dmesg -T | grep -iE "oom|killed|error|fail" | tail -20
```

---

### Сценарий 5: SSH access к control plane узлам

**Контекст**: Control plane узлы за additional firewall. Доступ через SSH tunnel.

**Настройка:**
```bash
# ~/.ssh/config

# Control plane через bastion + additional hop
Host cp-1 cp-2 cp-3
    ProxyJump bastion
    User admin
    IdentityFile ~/.ssh/cp_key

# Доступ к etcd
Host etcd-1 etcd-2 etcd-3
    ProxyJump bastion
    User admin
    IdentityFile ~/.ssh/etcd_key
```

**Диагностика etcd:**
```bash
# 1. Подключение к cp-1
ssh admin@cp-1

# 2. Проверка etcd
sudo ETCDCTL_API=3 etcdctl \
  --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/kubernetes/pki/etcd/ca.crt \
  --cert=/etc/kubernetes/pki/etcd/healthcheck-client.crt \
  --key=/etc/kubernetes/pki/etcd/healthcheck-client.key \
  endpoint health

# 3. Проверка лидерства
sudo ETCDCTL_API=3 etcdctl \
  --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/kubernetes/pki/etcd/ca.crt \
  --cert=/etc/kubernetes/pki/etcd/healthcheck-client.crt \
  --key=/etc/kubernetes/pki/etcd/healthcheck-client.key \
  endpoint status --write-out=table
```

---

### Сценарий 6: Автоматизация диагностики через SSH

**Скрипт для быстрой диагностики узла:**
```bash
#!/bin/bash
# node-diag.sh — Быстрая диагностика узла Kubernetes
# Использование: ./node-diag.sh <node-ip> [ssh-user]

NODE_IP=$1
SSH_USER=${2:-admin}
SSH_OPTS="-o ConnectTimeout=5 -o StrictHostKeyChecking=accept-new"

echo "=== Диагностика узла $NODE_IP ==="

# 1. Hostname и uptime
echo -e "\n--- Hostname & Uptime ---"
ssh $SSH_OPTS $SSH_USER@$NODE_IP "hostname; uptime"

# 2. Статус сервисов
echo -e "\n--- System Services ---"
ssh $SSH_OPTS $SSH_USER@$NODE_IP "systemctl is-active kubelet containerd"

# 3. Версии
echo -e "\n--- Versions ---"
ssh $SSH_OPTS $SSH_USER@$NODE_IP "kubelet --version; containerd --version"

# 4. Ресурсы
echo -e "\n--- Resources ---"
ssh $SSH_OPTS $SSH_USER@$NODE_IP "free -h | head -3; df -h / /var/lib/kubelet /var/lib/containerd"

# 5. Сеть
echo -e "\n--- Network ---"
ssh $SSH_OPTS $SSH_USER@$NODE_IP "ip -4 addr show scope global | head -5"

# 6. DNS
echo -e "\n--- DNS ---"
ssh $SSH_OPTS $SSH_USER@$NODE_IP "cat /etc/resolv.conf | grep nameserver"

# 7. Ошибки в логах
echo -e "\n--- Recent kubelet errors ---"
ssh $SSH_OPTS $SSH_USER@$NODE_IP "journalctl -u kubelet --since '1 hour ago' --no-pager | grep -iE 'error|fail|panic' | tail -10"

# 8. OOM
echo -e "\n--- OOM ---"
ssh $SSH_OPTS $SSH_USER@$NODE_IP "dmesg -T | grep -i 'oom\|killed' | tail -5"

echo -e "\n=== Диагностика завершена ==="
```

**Использование:**
```bash
chmod +x node-diag.sh
./node-diag.sh 10.0.1.10 admin
./node-diag.sh 10.0.1.11 admin
```

---

### Сценарий 7: kubectl port-forward через bastion

**Контекст**: Доступ к сервисам внутри кластера через bastion.

**Настройка:**
```bash
# 1. Проброс API-сервера через bastion
ssh -L 6443:api-server:6443 admin@bastion

# 2. Настроить kubectl для использования локального порта
kubectl config set-cluster local-k8s --server=https://127.0.0.1:6443 --insecure-skip-tls-verify=true

# 3. Доступ к кластеру
kubectl get nodes --cluster=local-k8s
```

**Прямой kubectl port-forward:**
```bash
# Проброс сервиса через bastion (без SSH tunnel)
kubectl port-forward svc/monitoring-grafana 3000:3000

# Проброс конкретного пода
kubectl port-forward pod/etcd-cp1 2379:2379 -n kube-system
```

## Мониторинг и алертинг

### Метрики доступности

| Метрика | Описание | Типичный порог алерта |
| :--- | :--- | :--- |
| `probe_success` | SSH-доступ к узлу (blackbox exporter) | == 0持续 5 минут |
| `probe_duration_seconds` | Время SSH-подключения | > 5持续 |
| `kube_node_status_condition{condition="Ready"}` | Готовность узла | == 0持续 2 минуты |

### Примеры алертов

```yaml
groups:
  - name: ssh-access
    rules:
      - alert: NodeSSHUnreachable
        expr: probe_success{job="blackbox-ssh"} == 0
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "SSH-доступ к {{ $labels.instance }} потерян"
          description: "Узел недоступен по SSH более 5 минут."

      - alert: BastionDown
        expr: probe_success{job="blackbox-ssh",instance="bastion"} == 0
        for: 3m
        labels:
          severity: critical
        annotations:
          summary: "Bastion-host недоступен"
          description: "Bastion-host не отвечает — все SSH-подключения через него невозможны."
```

## Дополнительная информация

### Полезные команды

```bash
# SSH ProxyJump
ssh -J user@bastion user@target          # Подключение через bastion
ssh -J user@bastion1,user@bastion2 user@target  # Через два bastion

# SSH tunnel (local port forward)
ssh -L local_port:target:target_port user@bastion
ssh -L 6443:api-server:6443 admin@bastion   # API-сервер
ssh -L 10250:node-1:10250 admin@bastion     # kubelet

# SSH remote port forward
ssh -R remote_port:localhost:local_port user@bastion
ssh -R 8443:localhost:8443 admin@bastion     # Expose local service

# SSH dynamic port forward (SOCKS proxy)
ssh -D 1080 admin@bastion
# Теперь SOCKS-прокси на 127.0.0.1:1080

# Проверка SSH-подключения
ssh -v admin@node-1 2>&1 | grep -i "debug1\|debug2"
ssh -T admin@node-1 echo "connected"  # Пробный ping
```

### Связанные разделы

- **[Диагностика узла](./diagnostics.md)** — SSH как инструмент диагностики
- **[kubectld ebug node](../../../Kubernetes/Debugging/kubectl_debug.md)** — альтернатива SSH
- **[Bastion: SSH конфигурация](../../../Linux/Security/ssh/ssh_client_config.md)** — детальная настройка SSH
- **[Сетевые проблемы](./network_issues.md)** — когда SSH недоступен из-за сети
- **[Обслуживание узлов](./maintenance.md)** — SSH-доступ для drain/uncordon
- **[Безопасность SSH](../../../Linux/Security/ssh/ssh_overview.md)** — best practices
