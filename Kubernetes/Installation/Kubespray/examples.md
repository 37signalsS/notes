# Kubespray: Примеры конфигураций

## 1. Определения

**Addons** — дополнительные компоненты Kubernetes, устанавливаемые через Kubespray в пространство имен `kube-system`: Ingress, MetalLB, Dashboard. Подробнее: [Namespace](../../Base/namespace.md).

## 2. Основные концепции

### Системные компоненты в kube-system

После установки Kubespray разворачивает в `kube-system`:

| Компонент | Поды | Описание |
| :--- | :--- | :--- |
| **Control Plane** | `kube-apiserver-*`, `kube-controller-manager-*`, `kube-scheduler-*` | Статические поды управления кластером |
| **CNI** | `calico-node-*`, `cilium-*`, `flannel-*` | Сетевой плагин (зависит от `kube_network_plugin`) |
| **kube-proxy** | `kube-proxy-*` | Сетевой прокси (режим: `iptables` или `ipvs`) |
| **DNS** | `coredns-*`, `dns-autoscaler`, `nodelocaldns-*` | DNS-сервис кластера |
| **Addons** | `kubernetes-dashboard-*`, `nginx-ingress-*`, `metallb-*` | Опциональные компоненты |

Проверка системных подов описана в [разделе 3.3](#33-проверка-системных-подов).

## 3. Практические сценарии

### 3.1. Выделенные ноды для Ingress

Использование `taints` и `tolerations` для изоляции Ingress-подов на выделенных узлах. Механизм описан в [Taints and Tolerations](../../Scheduling/taints_and_tolerations.md).

**`group_vars/k8s-cluster/addons.yml`:**

```yaml
# Параметры Ingress-контроллера
ingress_nginx_enabled: true
ingress_nginx_host_network: true  # Прокидывает сетевой неймспейс узла

ingress_nginx_configmap:
  server-tokens: "false"           # Не показывать версию Nginx
  proxy-body-size: "2048m"         # Максимальный размер тела запроса
  proxy-buffer-size: "16k"         # Размер буфера для прокси
  worker-shutdown-timeout: "180s"  # Graceful shutdown воркеров

ingress_nginx_nodeselector:
  node-role.kubernetes.io/ingress: ""  # Запуск только на нодах с этой меткой

ingress_nginx_tolerations:
- key: "node-role.kubernetes.io/ingress"
  operator: "Exists"
  effect: "NoSchedule"
```

**`group_vars/all/kube-ingress.yml`** (создается пользователем):

```yaml
# Метка для нод из группы 'kube_ingress'
node_labels:
  node-role.kubernetes.io/ingress: ""

# Taint для этих же нод
node_taints:
  - "node-role.kubernetes.io/ingress:NoSchedule"
```

### 3.2. Конфигурация MetalLB

**MetalLB** — балансировщик нагрузки для bare-metal кластеров. Подробнее: [MetalLB](../../Networking/metallb.md).

**Пример конфигурации:**

**`group_vars/k8s-cluster/addons.yml`:**

```yaml
# Включение MetalLB
metallb_enabled: true
metallb_speaker_enabled: true

# Пулы IP-адресов
metallb_config:
  address_pools:
    primary:
      ip_range:
        - "5.75.169.149/32"
        - "91.99.78.20/32"
      # auto_assign: false  # Отключить авто-назначение для этого пула
```

**Параметры:**

| Параметр | Описание |
| :--- | :--- |
| `metallb_enabled` | Включает установку MetalLB |
| `metallb_speaker_enabled` | Включает компонент `speaker` для анонсирования IP (L2/BGP) |
| `metallb_config.address_pools` | Пулы IP-адресов для сервисов типа `LoadBalancer` |

> **Важно:** При использовании `kube-proxy` в режиме `ipvs` необходимо установить `strictARP: true` в конфигурации kube-proxy. См. [MetalLB](../../Networking/metallb.md).

### 3.3. Проверка системных подов

**Просмотр всех подов в kube-system:**

```bash
kubectl get pods -n kube-system -o wide
```

**Проверка версии компонента Control Plane:**

```bash
kubectl describe pod kube-apiserver-control-1 -n kube-system | grep Image
```

**Проверка CNI-плагина:**

```bash
kubectl get pods -n kube-system -l k8s-app=calico-node
# или для Flannel
kubectl get pods -n kube-system -l app=flannel
```

## 4. Дополнительная информация

См. также: [Обзор Kubespray](./overview.md), [Установка кластера](./kubespray_install/basic_concepts.md), [Управление кластером](./cluster_management.md), [Offline установка](./offline_installation/offline_definitions.md), [CNI и kube-proxy](../../Networking/Network/cni_kube_proxy_roles.md), [MetalLB](../../Networking/metallb.md), [Taints and Tolerations](../../Scheduling/taints_and_tolerations.md).
