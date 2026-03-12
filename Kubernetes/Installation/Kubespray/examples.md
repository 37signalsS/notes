# Kubespray: Примеры конфигураций

## 1. Определения

**Системные поды** — поды, развертываемые в пространстве имен `kube-system` для работы кластера Kubernetes.

**Addons** — дополнительные компоненты, устанавливаемые в кластер (Ingress, MetalLB, Dashboard).

## 2. Основные концепции

### Системные компоненты

После установки в `kube-system` развертываются:

* **Control Plane (Static Pods):** `kube-apiserver-*`, `kube-controller-manager-*`, `kube-scheduler-*`.
* **Сетевые компоненты:** CNI-плагин (Calico, Cilium, Flannel), `kube-proxy-*`.
* **DNS и сервисы:** `coredns-*`, `dns-autoscaler`, `nodelocaldns-*`.
* **Дополнения (Addons):** `kubernetes-dashboard-*`, Ingress-контроллер и др.

Подробнее о пространствах имен: [Namespace](../../Base/namespace.md).

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

* [Обзор Kubespray](./overview.md) — определения и основные концепции.
* [Установка кластера](./installation.md) — развертывание кластера.
* [Управление кластером](./cluster_management.md) — масштабирование и обновление.
* [CNI, kube-proxy и их роли](../../Networking/Network/cni_kube_proxy_roles.md) — сетевые плагины.
* [MetalLB](../../Networking/metallb.md) — детальная документация по MetalLB.
* [Taints and Tolerations](../../Scheduling/taints_and_tolerations.md) — механизм изоляции подов.
