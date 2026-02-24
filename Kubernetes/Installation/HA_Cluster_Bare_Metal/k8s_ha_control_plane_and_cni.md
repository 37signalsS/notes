### 4. Настройка Control Plane

#### Инициализация первого мастер-узла

На **первом** мастере выполните:

```bash
# Замените LOAD_BALANCER_IP на VIP вашего балансировщика
# --pod-network-cidr требуется для многих CNI, например, Calico
sudo kubeadm init 
  --control-plane-endpoint "LOAD_BALANCER_IP:6443" 
  --pod-network-cidr=192.168.0.0/16 
  --upload-certs
```

* `--control-plane-endpoint`: Общая точка входа для всех мастеров (VIP).
* `--upload-certs`: Загружает сертификаты в кластер, чтобы их могли скачать другие мастера.
* `--pod-network-cidr`: Диапазон IP-адресов для подов. Убедитесь, что он не пересекается с другими сетями.

После успешной инициализации `kubeadm` выведет две команды `join`: одну для других мастеров, вторую для рабочих узлов. **Сохраните их.**

#### Настройка `kubectl`

Чтобы управлять кластером с мастер-узла:

```bash
mkdir -p $HOME/.kube
sudo cp -i /etc/kubernetes/admin.conf $HOME/.kube/config
sudo chown $(id -u):$(id -g) $HOME/.kube/config
```

#### Присоединение остальных мастер-узлов

На **втором и третьем** мастер-узлах выполните команду `kubeadm join` для мастеров, полученную ранее.

#### Присоединение рабочих узлов

На **каждом** рабочем узле выполните команду `kubeadm join` для воркеров.

### 5. Установка сетевого плагина (CNI)

Этот шаг выполняется **один раз** с любого мастер-узла после инициализации кластера. В качестве примера используем **Calico**.

```bash
# URL может меняться. Проверяйте совместимость Calico и Kubernetes в официальной документации.
# https://docs.projectcalico.org/getting-started/kubernetes/self-managed-on-premises/on-premises
kubectl apply -f https://raw.githubusercontent.com/projectcalico/calico/v3.31.0/manifests/calico.yaml
```

Проверьте, что все системные поды и узлы перешли в состояние `Running` и `Ready`:

```bash
kubectl get pods -n kube-system
kubectl get nodes
```
