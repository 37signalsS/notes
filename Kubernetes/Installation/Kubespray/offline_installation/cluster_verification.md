# Kubespray: Offline установка — Проверка кластера

## Определения

**Cluster Verification** — процесс валидации корректности установки и функционирования всех компонентов кластера Kubernetes после развёртывания через Kubespray в offline-режиме.

**Control Plane** — плоскость управления: `kube-apiserver`, `kube-controller-manager`, `kube-scheduler`, `etcd`.

**CNI (Container Network Interface)** — плагин сетевой связности подов; в данной инструкции — Cilium с заменой kube-proxy.

**Hubble** — инструмент наблюдаемости для Cilium, предоставляющий визуализацию сетевого трафика на базе eBPF.

**MetalLB** — балансировщик нагрузки для bare-metal кластеров, назначающий внешние IP сервисам типа `LoadBalancer`.

---

## Основные концепции

### Уровни проверки

1. **Базовая проверка** — узлы и системные поды
2. **Проверка CNI** — Cilium и Hubble
3. **Проверка LoadBalancer** — MetalLB
4. **Сетевая проверка** — DNS и связность подов
5. **Проверка runtime** — containerd на узлах

### Критерии успешной проверки

- Все узлы в статусе `Ready`
- Все системные поды в статусе `Running`
- Cilium показывает `Cluster health: N/N reachable`
- Hubble UI доступен
- MetalLB назначил внешний IP для LoadBalancer сервисов
- DNS резолвит имена сервисов

### Версии компонентов

| Компонент | Версия |
| :--- | :--- |
| Kubernetes | v1.34.3 |
| Cilium | v1.18.5 |
| MetalLB | v0.13.9 |
| Ingress-nginx | v1.13.3 |

---

## Практические сценарии

### Проверка узлов кластера

#### Статус узлов

```bash
kubectl get nodes -o wide
```

**Ожидаемый результат:**

```
NAME            STATUS   ROLES           AGE   VERSION   INTERNAL-IP     OS-IMAGE
master-1-k8s    Ready    control-plane   1h    v1.34.3   192.168.1.101   Ubuntu 24.04
master-2-k8s    Ready    control-plane   1h    v1.34.3   192.168.1.102   Ubuntu 24.04
master-3-k8s    Ready    control-plane   1h    v1.34.3   192.168.1.103   Ubuntu 24.04
node-1-k8s      Ready    <none>          1h    v1.34.3   192.168.1.104   Ubuntu 24.04
node-2-k8s      Ready    <none>          1h    v1.34.3   192.168.1.105   Ubuntu 24.04
```

#### Детальная информация о ноде

```bash
kubectl describe node master-1-k8s
```

**На что обратить внимание:**

- **Conditions:** Все должны быть `True` (кроме `NetworkUnavailable`)
- **Allocated resources:** Использование CPU/RAM
- **System Info:** Версия ядра, runtime

---

### Проверка системных компонентов

#### Pod'ы в kube-system

```bash
kubectl get pods -n kube-system
```

**Ключевые компоненты:**

| Компонент | Label selector |
| :--- | :--- |
| **Cilium** | `k8s-app=cilium` |
| **Cilium Operator** | `name=cilium-operator` |
| **Hubble Relay** | `k8s-app=hubble-relay` |
| **Hubble UI** | `k8s-app=hubble-ui` |
| **CoreDNS** | `k8s-app=kube-dns` |
| **kube-apiserver** | `component=kube-apiserver` |
| **kube-controller-manager** | `component=kube-controller-manager` |
| **kube-scheduler** | `component=kube-scheduler` |
| **etcd** | `component=etcd` |

#### Проверка Cilium

```bash
# Pod'ы Cilium
kubectl get pods -n kube-system -l k8s-app=cilium

# Статус Cilium
kubectl -n kube-system exec -it ds/cilium -- cilium status
```

**Ожидаемый вывод:**

```
KubeProxyReplacement:    True   [ens33  192.168.1.104 (Direct Routing)]
Cluster health:          5/5 reachable   (2026-03-13T10:00:00Z)
```

#### Проверка Hubble

```bash
# Pod'ы Hubble
kubectl get pods -n kube-system -l k8s-app=hubble

# Статус Hubble
kubectl -n kube-system exec -it ds/cilium -- hubble status
```

#### Проверка MetalLB

```bash
# Pod'ы MetalLB
kubectl get pods -n metallb-system

# Контроллер и speaker
kubectl get deployment -n metallb-system
kubectl get daemonset -n metallb-system
```

#### Проверка Ingress

```bash
# Pod'ы ingress-nginx
kubectl get pods -n ingress-nginx

# Ingress контроллер
kubectl get deployment -n ingress-nginx
```

---

### Проверка сетевых компонентов

#### Проверка MetalLB

```bash
# Статус IPAddressPool
kubectl get ipaddresspool -n metallb-system

# Статус L2Advertisement
kubectl get l2advertisement -n metallb-system

# Сервисы LoadBalancer
kubectl get svc -A | grep LoadBalancer
```

**Ожидаемый результат:**

```
NAME            TYPE           CLUSTER-IP      EXTERNAL-IP     PORT(S)
kubernetes      ClusterIP      10.233.0.1      <none>          443/TCP
hubble-ui       LoadBalancer   10.233.X.X      192.168.1.200   80:31234/TCP
```

#### Проверка DNS

```bash
# Тестовый pod для проверки DNS
kubectl run -it --rm dns-test --image=busybox:1.37 --restart=Never -- nslookup kubernetes.default
```

**Ожидаемый результат:**

```
Server:    10.233.0.10
Address 1: 10.233.0.10 kube-dns.kube-system.svc.cluster.local

Name:      kubernetes.default
Address 1: 10.233.0.1 kubernetes.default.svc.cluster.local
```

#### Проверка сетевых политик

```bash
# Список CiliumNetworkPolicy
kubectl get cnp --all-namespaces

# Статус политик
kubectl -n kube-system exec -it ds/cilium -- cilium policy get
```

---

### Проверка Hubble UI

#### Доступ через port-forward

```bash
kubectl port-forward -n kube-system svc/hubble-ui 8080:80
```

Открыть в браузере: `http://localhost:8080`

#### Доступ через Ingress

**Требуется DNS:** `hubble.k8s.domain.local → 192.168.1.200`

Открыть в браузере: `http://hubble.k8s.domain.local`

**Ожидаемый результат:** Веб-интерфейс Hubble с визуализацией сетевого трафика между подами.

---

### Проверка containerd на узлах

#### crictl команды

```bash
# На узле кластера

# Запущенные контейнеры
sudo crictl ps

# Запущенные поды на узле
sudo crictl pods

# Логи контейнера
sudo crictl logs <CONTAINER_ID>

# Статус образа
sudo crictl images | grep cilium
```

#### nerdctl команды

```bash
# Версия
nerdctl --version

# Список образов
nerdctl images

# Pull образа (если есть доступ к registry)
nerdctl pull <image>

# Save образа
nerdctl save -o <file.tar> <image>
```

---

### Диагностика проблем

#### Pod не запускается

```bash
# Описание pod
kubectl describe pod <pod-name> -n kube-system

# Логи pod
kubectl logs <pod-name> -n kube-system

# Логи предыдущей инстанции (если pod перезапускался)
kubectl logs <pod-name> -n kube-system --previous
```

#### Сетевые проблемы

```bash
# Проверка связности между подами
kubectl run test1 --image=busybox --rm -it --restart=Never -- ping -c 3 <pod-ip>

# Проверка DNS
kubectl run test2 --image=busybox --rm -it --restart=Never -- nslookup <service>
```

#### Проблемы с узлами

```bash
# Статус kubelet
systemctl status kubelet

# Логи kubelet
journalctl -u kubelet -f

# Статус containerd
systemctl status containerd
```

---

## Дополнительная информация

### Чек-лист успешной установки

- [ ] Все узлы в статусе `Ready`
- [ ] Все pod'ы в `kube-system` в статусе `Running`
- [ ] Cilium status показывает `Cluster health: 5/5 reachable`
- [ ] Hubble UI доступен
- [ ] MetalLB назначил внешний IP для LoadBalancer сервисов
- [ ] DNS резолвит имена сервисов
- [ ] Тестовые поды могут связываться друг с другом

### Связанные темы

Проверка кластера является завершающим этапом [развёртывания кластера](./step4_cluster_deploy.md) и предшествует [post-install управлению](./post_install_management.md). Детали настройки MetalLB и Ingress описаны в [шаге 5](./step5_metallb_ingress.md). Базовые термины — в [определениях offline-установки](./offline_definitions.md). Troubleshooting — в [соответствующем разделе](./troubleshooting.md). Общая информация о MetalLB — в [документации по балансировщику](../../../Networking/metallb.md).
