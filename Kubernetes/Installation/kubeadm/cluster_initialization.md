# Инициализация кластера через kubeadm

## Определения

**kubeadm init** — команда для инициализации первого узла Control Plane. Она выполняет проверку системы, генерирует удостоверяющий центр (CA), выпускает сертификаты и запускает компоненты Kubernetes в виде статических подов.

**kubeadm join** — команда для расширения кластера. Используется для присоединения новых узлов (мастеров с флагом `--control-plane` или воркеров).

**Control Plane Endpoint** — стабильная точка входа (VIP, DNS или адрес балансировщика) для доступа к API-серверу.

**Bootstrap Token** — временный секрет для аутентификации новых узлов. По умолчанию действует 24 часа.

**Discovery-token-ca-cert-hash** — хэш публичного ключа CA для проверки подлинности кластера при присоединении узла.

**Certificate Key** — ключ для шифрования сертификатов при их загрузке в кластер (необходим для автоматического присоединения других мастеров).

**pod-network-cidr** — диапазон IP-адресов для сети подов.

**service-cidr** — диапазон IP-адресов для ClusterIP сервисов.

---

## Основные концепции

### Процесс и фазы инициализации

Инициализация кластера через `kubeadm` — это набор атомарных фаз, которые можно запускать по отдельности для отладки (`kubeadm init phase <name>`):

1.  **Pre-flight checks**: Проверка CPU (мин. 2), RAM (мин. 2ГБ), отключения swap и доступности портов (6443, 2379-2380, 10250).
2.  **Certs generation**: Создание TLS-сертификатов в `/etc/kubernetes/pki` (ca, apiserver, etcd, front-proxy).
3.  **Kubeconfig generation**: Создание конфигов для `admin.conf`, `kubelet.conf`, `controller-manager.conf` и `scheduler.conf`.
4.  **Control plane preparation**: Генерация манифестов статических подов в `/etc/kubernetes/manifests`.
5.  **etcd initialization**: Запуск локального etcd (если не настроен внешний).
6.  **Wait control plane**: Ожидание появления API-сервера.
7.  **Upload-config/certs**: Загрузка конфигурации в ConfigMap `kubeadm-config` и (опционально) сертификатов в секреты.
8.  **Mark-control-plane**: Установка меток и Taints (по умолчанию мастер не запускает пользовательские поды).
9.  **Bootstrap-token**: Генерация токенов для фазы `join`.
10. **Addon**: Деплой CoreDNS и kube-proxy.

### Ключевые параметры (флаги) инициализации

| Флаг | Назначение | Пример |
| :--- | :--- | :--- |
| `--control-plane-endpoint` | Адрес балансировщика/VIP для HA-кластера | `k8s-api.example.com:7443` |
| `--upload-certs` | Автоматическая загрузка сертификатов для других мастеров | — |
| `--pod-network-cidr` | Сеть для подов (зависит от CNI) | `10.244.0.0/16` |
| `--service-cidr` | Сеть для сервисов | `10.96.0.0/12` |
| `--apiserver-advertise-address` | IP, на котором API-сервер будет доступен другим узлам | `192.168.1.10` |
| `--cri-socket` | Путь к сокету Runtime | `unix:///run/containerd/containerd.sock` |
| `--kubernetes-version` | Выбор конкретной версии Kubernetes | `v1.36.0` |

### Конфигурация через YAML (Рекомендуется)

Использование YAML позволяет сохранить настройки в системе контроля версий и настраивать параметры, недоступные через флаги (например, дополнительные SAN для сертификатов).

**Пример `init-config.yaml`:**
```yaml
apiVersion: kubeadm.k8s.io/v1beta4
kind: InitConfiguration
localAPIEndpoint:
  advertiseAddress: "192.168.1.10"
nodeRegistration:
  criSocket: "unix:///run/containerd/containerd.sock"
---
apiVersion: kubeadm.k8s.io/v1beta4
kind: ClusterConfiguration
kubernetesVersion: "v1.36.0"
controlPlaneEndpoint: "192.168.1.100:7443"
networking:
  podSubnet: "10.244.0.0/16"
  serviceSubnet: "10.96.0.0/12"
apiServer:
  certSANs:
    - "k8s-vip.local"
```

---

## Практические сценарии

### 1. Инициализация первого мастера (HA-подготовка)

```bash
sudo kubeadm init \
  --control-plane-endpoint "192.168.1.100:7443" \
  --pod-network-cidr=10.244.0.0/16 \
  --upload-certs \
  --cri-socket=unix:///run/containerd/containerd.sock
```

### 2. Управление токенами и ключами

Если вывод `kubeadm init` был потерян или токены истекли:
- **Создать команду join**: `kubeadm token create --print-join-command`
- **Перезагрузить сертификаты для новых мастеров**: `kubeadm init phase upload-certs --upload-certs`
- **Список токенов**: `kubeadm token list`

### 3. Настройка доступа kubectl

```bash
mkdir -p $HOME/.kube
sudo cp -i /etc/kubernetes/admin.conf $HOME/.kube/config
sudo chown $(id -u):$(id -g) $HOME/.kube/config

# Проверка
kubectl get nodes
```

### 4. Присоединение дополнительных узлов

**Control Plane (другие мастера):**
```bash
sudo kubeadm join 192.168.1.100:7443 --token <token> \
  --discovery-token-ca-cert-hash sha256:<hash> \
  --control-plane --certificate-key <key>
```

**Worker Nodes (рабочие узлы):**
```bash
sudo kubeadm join 192.168.1.100:7443 --token <token> \
  --discovery-token-ca-cert-hash sha256:<hash>
```

### 5. Установка сетевого плагина (CNI Calico)

```bash
curl -L https://raw.githubusercontent.com/projectcalico/calico/v3.32.1/manifests/calico.yaml -o calico.yaml
sed -i 's|192.168.0.0/16|10.244.0.0/16|g' calico.yaml
kubectl apply -f calico.yaml
```

---

## Дополнительная информация

### Диагностика и отладка

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `preflight` error | Swap включен | `sudo swapoff -a` |
| `etcd cluster unhealthy` | Проблемы с диском/сетью | Проверить `/var/lib/etcd` и задержки |
| `token expired` | Прошло >24 часов | Создать новый: `kubeadm token create` |
| `CRI runtime` not found | Неверный сокет | Указать `--cri-socket` |

**Команды диагностики:**
```bash
sudo journalctl -u kubelet -f            # Логи агента
sudo crictl ps -a                       # Список контейнеров через CRI
sudo crictl logs $(sudo crictl ps --name kube-apiserver -q) # Логи API
```

### Очистка и сброс узла (Cleanup)

Если нужно начать установку заново:
```bash
sudo kubeadm reset --force
# Ручная очистка
sudo rm -rf /etc/kubernetes/ /var/lib/etcd/ /var/lib/kubelet/ /var/lib/cni/ /etc/cni/net.d/
sudo iptables -F && sudo iptables -t nat -F && sudo iptables -t mangle -F && sudo iptables -X
sudo ip link delete cni0
sudo ip link delete flannel.1
```

### См. также
- **[Настройка HA API-сервера](./ha_concepts.md)**
- **[Управление сертификатами](../../Operations/certificate_management.md)**
- **[Обновление кластеров](../../Operations/upgrading_clusters.md)**
