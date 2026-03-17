# Инициализация HA кластера kubeadm

> **Примечание**: Подробная инструкция по инициализации Control Plane, добавлению worker-нод и установке CNI находится в файле [Control Plane & CNI](../../HA_Cluster_Bare_Metal/k8s_ha_control_plane_and_cni.md).

## Краткая инструкция

### Инициализация кластера

**На первом master-узле:**

```bash
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

### Присоединение узлов

**Control-plane узлы:**
```bash
sudo kubeadm join 192.168.122.189:7443 \
  --token <token> \
  --discovery-token-ca-cert-hash sha256:<hash> \
  --control-plane \
  --certificate-key <key>
```

**Worker-узлы:**
```bash
sudo kubeadm join 192.168.122.189:7443 \
  --token <token> \
  --discovery-token-ca-cert-hash sha256:<hash> \
  --cri-socket=unix:///run/containerd/containerd.sock
```

> **Примечание**: Worker-узлы не требуют флагов `--control-plane` и `--certificate-key`.

### Установка CNI (Calico)

Установка выполняется **один раз** после инициализации кластера:

```bash
# Скачиваем Calico
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

## Подробная инструкция

Для развёрнутой инструкции с мониторингом присоединения, проверкой Calico и troubleshooting см.:

- **[Control Plane & CNI](../../HA_Cluster_Bare_Metal/k8s_ha_control_plane_and_cni.md)** — пошаговая инструкция (Шаги 1-10)
- **[HA Cluster Overview](../../HA_Cluster_Bare_Metal/k8s_ha_cluster_overview.md)** — архитектурные концепции
- **[Node Preparation](../../HA_Cluster_Bare_Metal/k8s_ha_node_preparation.md)** — подготовка узлов
