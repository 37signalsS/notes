# Kubespray: Примеры конфигураций

## Определения

**Addons (Дополнения)** — вспомогательные компоненты Kubernetes, которые расширяют функциональность кластера (мониторинг, балансировщики, хранилища). В Kubespray аддоны обычно разворачиваются в пространство имен `kube-system` или специализированные неймспейсы (например, `metallb-system`).

**kube-system** — системное пространство имен для критически важных компонентов кластера и базовых дополнений (DNS, прокси, CNI).

**Helm** — менеджер пакетов для Kubernetes. Kubespray позволяет автоматически установить Helm на мастер-узлы для последующего ручного управления сложными приложениями.

## Основные концепции

### Управление дополнениями в Kubespray

Kubespray использует Ansible для управления жизненным циклом дополнений. Основной файл конфигурации — `inventory/mycluster/group_vars/k8s-cluster/addons.yml`.

**Типы дополнений:**
1. **Core Apps:** системные утилиты (Metrics Server, CoreDNS, Local Path Provisioner).
2. **Network Addons:** сетевые компоненты (MetalLB, Ingress-контроллеры).
3. **External Tools:** инструменты интеграции (Cert-manager, Node Feature Discovery).

> [!WARNING]
> Начиная с версии **v2.31.0 (2026)**, прямая поддержка `ingress-nginx` и `kubernetes-dashboard` была удалена из состава Kubespray. Рекомендуется использовать Helm для их установки.

### Состав системного пространства имен

Пример стандартного набора компонентов после развертывания:

| Компонент | Префикс подов | Назначение |
| :--- | :--- | :--- |
| **Control Plane** | `kube-apiserver-*` | Статические поды управления |
| **CNI** | `calico-node-*` / `cilium-*` | Сетевой плагин. См. [CNI и kube-proxy](../../Networking/Network/cni_kube_proxy_roles.md) |
| **DNS** | `coredns-*` | Резолвинг имен внутри кластера |
| **Metrics** | `metrics-server-*` | Сбор ресурсов для HPA и `kubectl top` |
| **DNS Cache** | `nodelocaldns-*` | Локальное кэширование DNS-запросов на узлах |

## Практические сценарии

### 1. Настройка Metrics Server

Metrics Server необходим для работы Horizontal Pod Autoscaler (HPA) и команды `kubectl top`.

**Конфигурация в `addons.yml`:**
```yaml
metrics_server_enabled: true
# Игнорировать проверку TLS сертификатов kubelet (часто нужно в Bare Metal)
metrics_server_kubelet_insecure_tls: true
# Настройка частоты сбора данных
metrics_server_metric_resolution: 15s
```

### 2. Конфигурация MetalLB (Layer 2)

MetalLB предоставляет External IP для сервисов типа `LoadBalancer` без использования облачных провайдеров. Подробнее: [MetalLB: Обзор и настройка](../../Networking/metallb.md).

**Конфигурация в `addons.yml`:**
```yaml
metallb_enabled: true
# Рекомендуется для большинства локальных сетей
metallb_protocol: "layer2"

# Определение пулов IP-адресов
metallb_config:
  address_pools:
    primary:
      ip_range:
        - "192.168.1.200-192.168.1.250"
      auto_assign: true
  # Обязательно для Layer 2
  l2_advertisements:
    default:
      ip_pools:
        - primary
```

### 3. Динамическое локальное хранилище (Local Path Provisioner)

Позволяет автоматически создавать `PersistentVolumes`, используя дисковое пространство узлов. Идеально для небольших кластеров или тестовых сред.

**Конфигурация в `addons.yml`:**
```yaml
local_path_provisioner_enabled: true
local_path_provisioner_storage_class: "local-path"
local_path_provisioner_reclaim_policy: Delete
local_path_provisioner_claim_root: /opt/local-path-provisioner
```

### 4. Оптимизация DNS: Node Local DNS

Уменьшает задержки и количество запросов к CoreDNS за счет запуска локального кэширующего агента на каждом узле.

**Конфигурация в `group_vars/k8s-cluster/k8s-cluster.yml`:**
```yaml
enable_nodelocaldns: true
# IP-адрес для локального прослушивания (обычно 169.254.20.10)
nodelocaldns_ip: 169.254.20.10
```

### 5. Использование Helm (для удаленных аддонов)

Если вам нужен Ingress NGINX в версиях 2.31+, включите Helm в Kubespray и установите чарт вручную.

**Включение Helm в `addons.yml`:**
```yaml
helm_enabled: true
```

**Пример установки Ingress после развертывания кластера:**
```bash
helm repo add ingress-nginx https://kubernetes.github.io/ingress-nginx
helm repo update
helm install my-ingress ingress-nginx/ingress-nginx --namespace ingress-nginx --create-namespace
```

### 6. Выделенные узлы для Ingress (Архивный метод)

Для версий Kubespray **ниже 2.31**, где Ingress еще встроен, можно использовать изоляцию:

**Конфигурация в `addons.yml`:**
```yaml
ingress_nginx_enabled: true
ingress_nginx_host_network: true
ingress_nginx_nodeselector:
  node-role.kubernetes.io/ingress: ""
ingress_nginx_tolerations:
- key: "node-role.kubernetes.io/ingress"
  operator: "Exists"
  effect: "NoSchedule"
```

## Дополнительная информация

- [Обзор Kubespray](./overview.md) — базовые принципы.
- [Установка кластера](./kubespray_install/basic_concepts.md) — пошаговое руководство.
- [MetalLB: Балансировщик для Bare-metal](../../Networking/metallb.md) — детальная настройка сети.
- [Persistent Volumes](../../Storage/pv_and_pvc.md) — работа с хранилищами.
- [Local Path Provisioner](../../Storage/local-path-provisioner.md) — детальное описание провизионера.
