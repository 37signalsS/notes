# Установка CNI в HA кластере

## Определения

**CNI (Container Network Interface)** — стандартный плагин для обеспечения сетевой связности между подами на разных узлах кластера.

**Calico** — популярный CNI-плагин с поддержкой NetworkPolicy, BGP-маршрутизации и policy-based управления сетью.

**pod-network-cidr** — диапазон IP-адресов для подов (не должен пересекаться с существующей инфраструктурой).

---

## Основные концепции

### Почему CNI устанавливается отдельно?

Kubernetes не включает сетевой плагин по умолчанию. Администратор выбирает CNI в зависимости от требований:

| Критерий | Flannel | Calico | Cilium |
| :--- | :--- | :--- | :--- |
| **Сложность** | Простая | Средняя | Высокая |
| **NetworkPolicy** | Нет | Да | Да |
| **Производительность** | Средняя (overlay) | Высокая (BGP) | Очень высокая (eBPF) |
| **Замена kube-proxy** | Нет | Нет (кроме eBPF режима) | Да |
| **Режим работы** | Overlay (VXLAN) | Overlay/BGP | eBPF/Direct Routing |
| **Рекомендация** | Dev/Test | **Production (bare-metal)** | Production (eBPF) |

**Рекомендации**:

- **Calico** — наиболее стабильное и функциональное решение для bare-metal, хорошая производительность, поддержка NetworkPolicy, проверенное решение
- **Flannel** — проще в настройке, но без поддержки NetworkPolicy, подходит для dev/test
- **Cilium** — современный CNI на базе eBPF, продвинутая безопасность, замена kube-proxy, но сложнее в настройке и отладке

Подробнее: [Выбор CNI](../../Networking/Network/CNI/selection_and_external_access.md), [eBPF режим](../../Networking/Network/CNI/ebpf.md)

---

## Практические сценарии

### Шаг 5: Установка CNI-плагина (Calico)

Установка выполняется **один раз** с любого мастер-узла после инициализации кластера. Master-нода будет в статусе `NotReady` до установки CNI.

```bash
# Скачиваем Calico
# ВЕРСИЯ: v3.28.0 — проверить совместимость с вашей версией Kubernetes
curl -L https://raw.githubusercontent.com/projectcalico/calico/v3.28.0/manifests/calico.yaml -o calico.yaml

# Меняем CIDR под наш pod-network-cidr
sed -i 's|192.168.0.0/16|100.64.0.0/16|g' calico.yaml

# Применяем
kubectl apply -f calico.yaml
```

> **Важно**:
>
> - Версия Calico должна соответствовать версии Kubernetes (проверьте в [официальной документации](https://docs.tigera.io/calico/latest/about/supported-releases))
> - CIDR в манифесте должен совпадать с `--pod-network-cidr` из `kubeadm init`
> - Изменение CIDR после применения невозможно без пересоздания CNI

**Альтернативные CNI**:

- **Cilium**: `kubectl apply -f https://raw.githubusercontent.com/cilium/cilium/master/install/kubernetes/quick-install.yaml`
- **Flannel**: `kubectl apply -f https://raw.githubusercontent.com/flannel-io/flannel/master/Documentation/kube-flannel.yml`

### Шаг 6: Проверка состояния кластера

```bash
# Проверка системных подов (все должны быть Running)
kubectl get pods -n kube-system

# Проверка узлов (все должны быть Ready после установки CNI)
kubectl get nodes

# Проверка компонентов Control Plane
kubectl get pods -n kube-system -l component=kube-apiserver
kubectl get pods -n kube-system -l component=kube-controller-manager
kubectl get pods -n kube-system -l component=kube-scheduler
kubectl get pods -n kube-system -l component=etcd

# Проверка CNI подов (Calico)
kubectl get pods -n kube-system -l k8s-app=calico-node
```

**Ожидаемый результат**:

- Все системные поды в статусе `Running`
- Все узлы в статусе `Ready`
- 3 пода `etcd`, 3 пода `kube-apiserver` (для HA кластера)
- Поды Calico на каждом узле

---

## Дополнительная информация

### Связанные документы

- **Обзор HA**: [HA Cluster Overview](./k8s_ha_cluster_overview.md)
- **Control Plane**: [Control Plane Initialization](./control_plane_initialization.md)
- **Node Joining**: [Node Joining](./node_joining.md)
- **CNI Overview**: [CNI Overview](../../Networking/Network/CNI/definitions.md)
- **Выбор CNI**: [Выбор CNI](../../Networking/Network/CNI/selection_and_external_access.md)
- **eBPF режим**: [eBPF режим](../../Networking/Network/CNI/ebpf.md)
- **Calico Documentation**: [Calico Documentation](https://docs.tigera.io/calico/latest/)
