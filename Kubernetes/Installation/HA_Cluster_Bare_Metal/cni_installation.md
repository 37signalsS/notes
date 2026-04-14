# Установка CNI в HA кластере

## Определения

**CNI (Container Network Interface)** — стандартный плагин для обеспечения сетевой связности между подами на разных узлах кластера. Kubernetes не включает CNI по умолчанию — администратор выбирает плагин в зависимости от требований ([подробнее о выборе CNI](../../Networking/Network/CNI/selection_and_external_access.md)).

**pod-network-cidr** — диапазон IP-адресов для подов, указываемый при инициализации кластера (`kubeadm init --pod-network-cidr`). Не должен пересекаться с существующей инфраструктурой.

---

## Основные концепции

### Почему CNI устанавливается отдельно

Kubernetes делегирует сетевую функциональность внешним плагинам через CNI-спецификацию. До установки CNI все узлы кластера находятся в статусе `NotReady`, а поды не могут быть запланированы.

**Рекомендация для bare-metal HA кластеров**: Calico — проверенное решение с поддержкой BGP-маршрутизации и NetworkPolicy ([сравнение CNI](../../Networking/Network/CNI/selection_and_external_access.md)).

### Версии и совместимость

| Компонент | Версия | Примечание |
| :--- | :--- | :--- |
| **Calico** | v3.31.x | Актуальная стабильная ветка (поддерживается до 2026) |
| **Kubernetes** | 1.29–1.31 | Calico v3.31 совместим с N-2 версиями K8s |

> **Важно**: Calico следует политике N-2 — каждая версия поддерживает текущую и две предыдущие версии Kubernetes. Проверяйте [матрицу совместимости](https://docs.tigera.io/calico/latest/about/supported-releases) перед установкой.

---

## Практические сценарии

### Шаг 5: Установка Calico

Установка выполняется **один раз** с любого мастер-узла после `kubeadm init`. Master-ноды будут в статусе `NotReady` до применения CNI.

```bash
# 1. Скачиваем манифест Calico
# Замените v3.31.4 на актуальную версию из официальной документации
curl -L https://raw.githubusercontent.com/projectcalico/calico/v3.31.4/manifests/calico.yaml -o calico.yaml

# 2. Заменяем CIDR на ваш pod-network-cidr
# (должен совпадать с --pod-network-cidr из kubeadm init)
sed -i 's|192.168.0.0/16|100.64.0.0/16|g' calico.yaml

# 3. Применяем манифест
kubectl apply -f calico.yaml
```

**Критические требования**:

- CIDR в манифесте **должен совпадать** с `--pod-network-cidr` из `kubeadm init`
- Изменение CIDR после применения невозможно без пересоздания CNI
- Версия Calico должна соответствовать версии Kubernetes

**Альтернативные CNI** (не рекомендуются для production bare-metal):

- **Flannel**: `kubectl apply -f https://raw.githubusercontent.com/flannel-io/flannel/master/Documentation/kube-flannel.yml` — проще в настройке, но без NetworkPolicy
- **Cilium**: `kubectl apply -f https://raw.githubusercontent.com/cilium/cilium/master/install/kubernetes/quick-install.yaml` — eBPF-режим с заменой kube-proxy, сложнее в отладке

### Шаг 6: Проверка состояния кластера

```bash
# Проверка всех системных подов
kubectl get pods -n kube-system

# Проверка узлов (должны быть Ready после установки CNI)
kubectl get nodes

# Проверка подов Calico
kubectl get pods -n kube-system -l k8s-app=calico-node

# Детальная проверка компонентов Control Plane
kubectl get pods -n kube-system -l component=kube-apiserver
kubectl get pods -n kube-system -l component=kube-controller-manager
kubectl get pods -n kube-system -l component=kube-scheduler
kubectl get pods -n kube-system -l component=etcd
```

**Ожидаемый результат для HA кластера**:

| Компонент | Количество | Статус |
| :--- | :--- | :--- |
| `etcd` | 3 | Running |
| `kube-apiserver` | 3 | Running |
| `kube-controller-manager` | 2+ | Running |
| `kube-scheduler` | 2+ | Running |
| `calico-node` | По одному на узел | Running |
| Все узлы | — | Ready |

---

## Дополнительная информация

### Отладка проблем с CNI

```bash
# Логи Calico на узле
kubectl logs -n kube-system -l k8s-app=calico-node

# Проверка IPAM (выделение IP)
kubectl exec -n kube-system <calico-pod> -- calicoctl ipam show

# Диагностика сетевых политик
kubectl exec -n kube-system <calico-pod> -- calicoctl get networkpolicy
```

### Интеграция с процессом развёртывания HA кластера

Установка CNI — **шаг 5** после [инициализации Control Plane](./control_plane_initialization.md) и перед [подключением узлов](./node_joining.md). Подробнее об архитектуре HA кластера — в [обзоре](./k8s_ha_cluster_overview.md). Теоретические основы CNI и разделение ролей с kube-proxy описаны в [документации по CNI](../../Networking/Network/CNI/definitions.md), сравнение плагинов — в [руководстве по выбору CNI](../../Networking/Network/CNI/selection_and_external_access.md). Официальная документация Calico: <https://docs.tigera.io/calico/latest/>
