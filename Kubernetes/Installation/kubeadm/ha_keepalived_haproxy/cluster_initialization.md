# Инициализация HA кластера kubeadm

## Инициализация кластера

**На первом master-узле:**

```bash
sudo kubeadm init \
  --control-plane-endpoint "192.168.122.189:7443" \
  --upload-certs
```

**На остальных master-узлах:**

```bash
# Используйте команду из вывода kubeadm init
sudo kubeadm join 192.168.122.189:7443 \
  --token <token> \
  --discovery-token-ca-cert-hash sha256:<hash> \
  --control-plane \
  --certificate-key <key>
```

**На worker-узлах:**

```bash
sudo kubeadm join 192.168.122.189:7443 \
  --token <token> \
  --discovery-token-ca-cert-hash sha256:<hash>
```

## Проверка

**Проверка VIP:**

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

- [Быстрый старт с kubeadm](./kubeadm_quickstart.md)
- [HA кластер на bare metal](../HA_Cluster_Bare_Metal/k8s_ha_cluster_overview.md)
- [Keepalived обзор](../../../Networking/ServicesAndTools/keepalived_overview.md)
- [HAProxy обзор](../../../WebServers/Haproxy/haproxy_overview.md)
