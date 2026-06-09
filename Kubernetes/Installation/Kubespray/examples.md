# Kubespray: Примеры конфигураций

## Определения

**Addons (Дополнения)** — вспомогательные компоненты Kubernetes, которые расширяют функциональность кластера (Ingress-контроллеры, балансировщики, дашборды). В Kubespray аддоны обычно разворачиваются в пространство имен `kube-system`. Подробнее: [Namespace (Пространства имен)](../../Base/namespace.md).

**kube-system** — зарезервированное пространство имен для системных компонентов Kubernetes и дополнений, обеспечивающих работу инфраструктуры кластера.

## Основные концепции

### Управление дополнениями в Kubespray

Kubespray управляет установкой дополнений через Ansible-переменные в каталоге `group_vars/k8s-cluster/addons.yml`. Большинство аддонов по умолчанию выключены (`enabled: false`).

### Типовой состав системного пространства имен

После успешной установки кластера через Kubespray, в `kube-system` присутствуют следующие компоненты:

| Компонент | Префикс подов | Описание |
| :--- | :--- | :--- |
| **Control Plane** | `kube-apiserver-*`, `kube-controller-manager-*`, `kube-scheduler-*` | Основные узлы управления кластером (статические поды) |
| **CNI** | `calico-node-*`, `cilium-*`, `flannel-*` | Сетевой плагин. См. [CNI и kube-proxy](../../Networking/Network/cni_kube_proxy_roles.md) |
| **kube-proxy** | `kube-proxy-*` | Обеспечивает работу сервисов через iptables или IPVS |
| **DNS** | `coredns-*`, `dns-autoscaler`, `nodelocaldns-*` | Система доменных имен внутри кластера |
| **Addons** | `kubernetes-dashboard-*`, `nginx-ingress-*`, `metallb-*` | Опциональные компоненты, включенные пользователем |

## Практические сценарии

### Выделенные узлы для Ingress

Изоляция Ingress-контроллеров на выделенных узлах (DMZ) повышает безопасность и предсказуемость производительности. Для этого используются механизмы `taints` и `tolerations`. Подробнее: [Taints and Tolerations (Тейнты и толерантности)](../../Scheduling/taints_and_tolerations.md).

**Конфигурация в `group_vars/k8s-cluster/addons.yml`:**

```yaml
# Активация Ingress NGINX
ingress_nginx_enabled: true
ingress_nginx_host_network: true

ingress_nginx_configmap:
  server-tokens: "false"
  proxy-body-size: "2048m"

# Настройка запуска только на определенных узлах
ingress_nginx_nodeselector:
  node-role.kubernetes.io/ingress: ""

ingress_nginx_tolerations:
- key: "node-role.kubernetes.io/ingress"
  operator: "Exists"
  effect: "NoSchedule"
```

**Настройка меток и тейнтов в `inventory/mycluster/group_vars/all/all.yml` или через inventory:**

```yaml
# Автоматическое назначение меток и тейнтов при установке
node_labels:
  node-role.kubernetes.io/ingress: ""

node_taints:
  - "node-role.kubernetes.io/ingress:NoSchedule"
```

### Конфигурация MetalLB

MetalLB позволяет использовать сервисы типа `LoadBalancer` в средах без облачного провайдера. Подробнее: [MetalLB: Обзор и настройка](../../Networking/metallb.md).

**Конфигурация в `group_vars/k8s-cluster/addons.yml`:**

```yaml
# Включение MetalLB
metallb_enabled: true
metallb_speaker_enabled: true

# Определение пулов IP-адресов
metallb_config:
  address_pools:
    primary:
      ip_range:
        - "192.168.1.200/32" # Одиночный IP
        - "192.168.1.210-192.168.1.220" # Диапазон
```

**Важное требование для IPVS:**
При использовании `kube-proxy` в режиме `ipvs` необходимо установить `strictARP: true`. В Kubespray это делается автоматически при включении MetalLB, но можно задать явно:
`kube_proxy_strict_arp: true`

### Проверка состояния системных компонентов

**Просмотр всех подов в системном пространстве имен:**

```bash
kubectl get pods -n kube-system -o wide
```

**Проверка статуса CNI-плагина (на примере Calico):**

```bash
kubectl get pods -n kube-system -l k8s-app=calico-node
```

**Проверка версии API-сервера:**

```bash
kubectl describe pod kube-apiserver-control-1 -n kube-system | grep Image
# → Image: registry.k8s.io/kube-apiserver:v1.29.0
```

## Дополнительная информация

- [Обзор Kubespray](./overview.md) — общие принципы и возможности.
- [Установка кластера](./kubespray_install/basic_concepts.md) — пошаговое руководство по развертыванию.
- [MetalLB: Балансировщик для Bare-metal](../../Networking/metallb.md) — глубокое погружение в работу MetalLB.
- [CNI и kube-proxy](../../Networking/Network/cni_kube_proxy_roles.md) — описание сетевой подсистемы.
- [Taints and Tolerations](../../Scheduling/taints_and_tolerations.md) — механизмы планирования подов.
