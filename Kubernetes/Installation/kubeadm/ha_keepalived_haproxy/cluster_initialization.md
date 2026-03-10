# Инициализация HA кластера kubeadm

> **Примечание**: Подробная инструкция по инициализации Control Plane и установке CNI находится в файле [Control Plane & CNI](../../HA_Cluster_Bare_Metal/k8s_ha_control_plane_and_cni.md).

## Инициализация кластера

### Параметры инициализации

**На первом master-узле:**

```bash
# Важно: выбираем CIDR, не пересекающиеся с вашей сетью
# --pod-network-cidr=100.64.0.0/16 - для pod'ов
# --service-cidr=100.65.0.0/16 - для сервисов

sudo kubeadm init \
  --control-plane-endpoint "192.168.122.189:7443" \
  --pod-network-cidr=100.64.0.0/16 \
  --service-cidr=100.65.0.0/16 \
  --upload-certs \
  --apiserver-advertise-address=192.168.1.1 \
  --apiserver-bind-port=6443 \
  --cri-socket=unix:///run/containerd/containerd.sock
```

**Параметры**:

- `--control-plane-endpoint` — VIP балансировщика (Keepalived + HAProxy)
- `--pod-network-cidr` — диапазон IP для подов (требуется для CNI)
- `--service-cidr` — диапазон IP для сервисов (по умолчанию `10.96.0.0/12`)
- `--upload-certs` — загрузка сертификатов в кластер для других мастеров
- `--apiserver-advertise-address` — IP для публикации API
- `--cri-socket` — CRI-сокет (для containerd: `/run/containerd/containerd.sock`)

**Результат**:

- `kubeadm` выведет **две команды `join`**:
  1. Для других мастер-узлов (с `--control-plane` и `--certificate-key`)
  2. Для worker-узлов (без дополнительных флагов)

> **Важно**: Сохраните вывод команды! Команды `join` содержат одноразовые токены.

### Настройка kubectl

```bash
# Выполняется как обычный пользователь
mkdir -p $HOME/.kube
sudo cp -i /etc/kubernetes/admin.conf $HOME/.kube/config
sudo chown $(id -u):$(id -g) $HOME/.kube/config

# Проверка
kubectl cluster-info
kubectl get nodes
```

> **Примечание**: Статус `NotReady` — это нормально до установки CNI.

### Присоединение мастер-узлов

**На остальных master-узлах:**

```bash
# Используйте команду из вывода kubeadm init
sudo kubeadm join 192.168.122.189:7443 \
  --token <token> \
  --discovery-token-ca-cert-hash sha256:<hash> \
  --control-plane \
  --certificate-key <key>
```

### Присоединение worker-узлов

**На worker-узлах:**

```bash
sudo kubeadm join 192.168.122.189:7443 \
  --token <token> \
  --discovery-token-ca-cert-hash sha256:<hash>
```

### Установка CNI (Calico)

Установка выполняется **один раз** после инициализации кластера:

```bash
# Скачиваем Calico
# ВЕРСИЯ: проверить совместимость с вашей версией Kubernetes
curl -L https://raw.githubusercontent.com/projectcalico/calico/v3.28.0/manifests/calico.yaml -o calico.yaml

# Меняем CIDR под наш pod-network-cidr
sed -i 's|192.168.0.0/16|100.64.0.0/16|g' calico.yaml

# Применяем
kubectl apply -f calico.yaml
```

> **Важно**: Версия Calico должна соответствовать версии Kubernetes. Проверьте в [официальной документации](https://docs.tigera.io/calico/latest/about/supported-releases).

После установки CNI узлы перейдут в статус `Ready`:

```bash
kubectl get nodes
# NAME     STATUS   ROLES           AGE   VERSION
# master   Ready    control-plane   10m   v1.34.3
```

Подробнее: [Control Plane & CNI](../../HA_Cluster_Bare_Metal/k8s_ha_control_plane_and_cni.md).

## Проверка

### Проверка VIP

```bash
# На MASTER-узле VIP должен быть активен
ip a | grep 192.168.122.189

# Тест failover: остановить keepalived на MASTER
sudo systemctl stop keepalived
# VIP должен переместиться на BACKUP
```

**Проверка HAProxy:**

```bash
# Статистика (если включена)
curl http://<master-ip>:8404/stats

# Проверка доступности API через VIP
curl -k https://192.168.122.189:7443/healthz
```

**Проверка кластера:**

```bash
kubectl get nodes
kubectl get pods -n kube-system
```

## Troubleshooting

| Проблема | Диагностика | Решение |
| :--- | :--- | :--- |
| **VIP не назначается** | `systemctl status keepalived`, `journalctl -u keepalived` | Проверить интерфейс, priority, `virtual_router_id` |
| **HAProxy не стартует** | `haproxy -c -f /etc/haproxy/haproxy.cfg` | Проверить синтаксис, доступность бэкендов |
| **API недоступен через VIP** | `curl -k https://VIP:7443/healthz` | Проверить `ip_nonlocal_bind`, firewall |
| **Бэкенды DOWN** | `curl http://IP:8404/stats` | Проверить доступность API Server на узлах |
| **VRRP конфликты** | `tcpdump -i <interface> vrrp` | Убедиться в уникальности `virtual_router_id` |

## Связанные темы

- **Control Plane & CNI**: [Подробная инструкция](../../HA_Cluster_Bare_Metal/k8s_ha_control_plane_and_cni.md)
- **HA концепции**: [HA Concepts](./ha_concepts.md)
- **Keepalived + HAProxy**: [Установка](./keepalived_haproxy_setup.md)
- **HA кластер на bare metal**: [HA Overview](../../HA_Cluster_Bare_Metal/k8s_ha_cluster_overview.md)
- **Keepalived обзор**: [Keepalived](../../../Networking/ServicesAndTools/keepalived_overview.md)
- **HAProxy обзор**: [HAProxy](../../../WebServers/Haproxy/haproxy_overview.md)
