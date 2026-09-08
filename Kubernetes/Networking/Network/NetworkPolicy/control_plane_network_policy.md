# NetworkPolicy для Control Plane Components

## Определения

**Control Plane** — совокупность компонентов Kubernetes, управляющих кластером: API Server, etcd, Controller Manager, Scheduler, Cloud Controller Manager. Эти компоненты работают как статические поды на master-узлах и требуют строгой сетевой изоляции для предотвращения несанкционированного доступа.

**API Server (kube-apiserver)** — центральная точка входа в кластер. Принимает REST-запросы от kubectl, kubelet, контроллеров и scheduler. Работает на порту 6443 (HTTPS). Все взаимодействие с кластером проходит через API Server.

**etcd** — распределённое хранилище состояния кластера. Работает на порту 2379 (клиентский) и 2380 (peer). Только API Server имеет прямой доступ к etcd. Доступ к etcd извне — критическая уязвимость.

**Controller Manager** — менеджер контрольных петель (replication, endpoint, service account). Работает на порту 10257 (HTTPS). Взаимодействует с API Server, но не принимает входящих соединений от подов.

**Scheduler** — планировщик подов на узлы. Работает на порту 10259 (HTTPS). Аналогично Controller Managerу — только исходящие соединения к API Server.

**Static Pod** — под, управляемый напрямую kubelet на узле, а не API Server. Control Plane компоненты通常 запускаются как static pods через манифесты в `/etc/kubernetes/manifests/`.

## Базовые Концепции

### Зачем нужна NetworkPolicy для Control Plane

В стандартной конфигурации (kubeadm) control plane компоненты доступны со всех узлов кластера:

```
┌─────────────────────────────────────────────────────────┐
│                    Control Plane                         │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐     │
│  │ API Server  │  │    etcd     │  │  Scheduler  │     │
│  │ :6443       │  │ :2379/:2380 │  │ :10259      │     │
│  └─────────────┘  └─────────────┘  └─────────────┘     │
│         ▲               ▲               ▲               │
│         │               │               │               │
│         └───────────────┴───────────────┘               │
│                    │                                     │
│         Доступно со ВСЕХ узлов кластера                 │
└─────────────────────────────────────────────────────────┘
```

**Проблема:** Без NetworkPolicy любой под на любом узле может обращаться к API Server (6443) и, при наличии ошибок конфигурации, potentially к etcd.

**Решение:** Применение NetworkPolicy для ограничения доступа к control plane компонентам.

### Принцип минимальных привилегий для Control Plane

| Компонент | Кто должен иметь доступ | Порты | Направление |
| :--- | :--- | :--- | :--- |
| **API Server** | kubelet, контроллеры, scheduler, kubectl, все поды (для SA token) | 6443 | Ingress |
| **etcd** | Только API Server | 2379, 2380 | Ingress |
| **Controller Manager** | Только API Server (outbound) | 10257 | Нет inbound |
| **Scheduler** | Только API Server (outbound) | 10259 | Нет inbound |
| **kubelet** | API Server, monitoring | 10250 | Ingress |

### Порядок фильтрации для Control Plane

```
Под приложения → [NetworkPolicy пода] → [NetworkPolicy control plane] → API Server
                                                                     │
                                                                     ├── Ingress: разрешить от kubelet, controller manager
                                                                     ├── Ingress: разрешить от monitoring (Prometheus)
                                                                     └── Ingress: заблокировать от подов приложений (если не нужно)
```

## Практические сценарии

### Сценарий 1: Изоляция etcd (критически важно)

etcd должен быть доступен ТОЛЬКО из API Server. В стековой топологии (kubeadm) etcd работает на тех же узлах:

```yaml
# NetworkPolicy для etcd (если etcd как Deployment/StatefulSet)
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-etcd-only-from-apiserver
  namespace: kube-system
spec:
  podSelector:
    matchLabels:
      component: etcd
  policyTypes:
  - Ingress
  ingress:
  # Только от API Server
  - from:
    - namespaceSelector: {}
      podSelector:
        matchLabels:
          component: kube-apiserver
    ports:
    - protocol: TCP
      port: 2379  # клиентский порт
    - protocol: TCP
      port: 2380  # peer-порты (только для кластера etcd)
```

**Для стековой топологии (kubeadm):**

etcd работает как static pod, поэтому стандартная NetworkPolicy не применяется к нему (hostNetwork). Вместо этого используется firewall на уровне узла:

```bash
# На master-узле: ограничение доступа к etcd через iptables
iptables -A INPUT -p tcp --dport 2379 -s <apiserver-ip> -j ACCEPT
iptables -A INPUT -p tcp --dport 2379 -j DROP

iptables -A INPUT -p tcp --dport 2380 -s <etcd-peer-ip> -j ACCEPT
iptables -A INPUT -p tcp --dport 2380 -j DROP
```

### Сценарий 2: NetworkPolicy для API Server

API Server должен принимать трафик от:

1. **kubelet** на каждом узле (port 10250)
2. **Контроллеров и scheduler** (outbound from these components)
3. **Подов приложений** (для ServiceAccount token и API calls)
4. **Monitoring** (Prometheus scrape)
5. **kubectl** с рабочих станций

```yaml
# NetworkPolicy для API Server
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-apiserver-ingress
  namespace: kube-system
spec:
  podSelector:
    matchLabels:
      component: kube-apiserver
  policyTypes:
  - Ingress
  ingress:
  # От kubelet на всех узлах (health checks, token reviews)
  - from:
    - ipBlock:
        cidr: 10.0.0.0/8  # CIDR узлов кластера
    ports:
    - protocol: TCP
      port: 6443
  # От monitoring (Prometheus)
  - from:
    - namespaceSelector:
        matchLabels:
          kubernetes.io/metadata.name: monitoring
      podSelector:
        matchLabels:
          app: prometheus
    ports:
    - protocol: TCP
      port: 6443
  # От подов приложений (ServiceAccount token requests)
  - from:
    - namespaceSelector: {}  # все namespace
    ports:
    - protocol: TCP
      port: 6443
```

### Сценарий 3: Изоляция Controller Manager и Scheduler

Controller Manager (10257) и Scheduler (10259) не должны принимать входящий трафик от подов:

```yaml
# NetworkPolicy: блокировка входящего трафика к Controller Manager
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: deny-controller-manager-ingress
  namespace: kube-system
spec:
  podSelector:
    matchLabels:
      component: kube-controller-manager
  policyTypes:
  - Ingress
  ingress: []  # Полный запрет входящего трафика
---
# NetworkPolicy: блокировка входящего трафика к Scheduler
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: deny-scheduler-ingress
  namespace: kube-system
spec:
  podSelector:
    matchLabels:
      component: kube-scheduler
  policyTypes:
  - Ingress
  ingress: []  # Полный запрет входящего трафика
```

### Сценарий 4: NetworkPolicy для kubelet

kubelet работает на каждом узле и принимает трафик от API Server (port 10250):

```yaml
# NetworkPolicy для kubelet (если kubelet как DaemonSet)
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-kubelet-from-apiserver
  namespace: kube-system
spec:
  podSelector:
    matchLabels:
      k8s-app: kubelet
  policyTypes:
  - Ingress
  ingress:
  # Только от API Server
  - from:
    - namespaceSelector: {}
      podSelector:
        matchLabels:
          component: kube-apiserver
    ports:
    - protocol: TCP
      port: 10250
```

### Сценарий 5: Default Deny для kube-system

Полная изоляция namespace `kube-system` с явным разрешением необходимых компонентов:

```yaml
# 1. Default Deny All
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: default-deny-all
  namespace: kube-system
spec:
  podSelector: {}
  policyTypes:
  - Ingress
  - Egress
---
# 2. Разрешить DNS (обязательно)
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-dns
  namespace: kube-system
spec:
  podSelector: {}
  policyTypes:
  - Egress
  egress:
  - ports:
    - protocol: UDP
      port: 53
    - protocol: TCP
      port: 53
---
# 3. Разрешить API Server принимать трафик
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-apiserver
  namespace: kube-system
spec:
  podSelector:
    matchLabels:
      component: kube-apiserver
  policyTypes:
  - Ingress
  ingress:
  - from:
    - ipBlock:
        cidr: 10.0.0.0/8  # CIDR узлов
    ports:
    - protocol: TCP
      port: 6443
---
# 4. Разрешить etcd только от API Server
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-etcd
  namespace: kube-system
spec:
  podSelector:
    matchLabels:
      component: etcd
  policyTypes:
  - Ingress
  ingress:
  - from:
    - podSelector:
        matchLabels:
          component: kube-apiserver
    ports:
    - protocol: TCP
      port: 2379
    - protocol: TCP
      port: 2380
---
# 5. Разрешить monitoring доступ к метрикам
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-monitoring
  namespace: kube-system
spec:
  podSelector: {}
  policyTypes:
  - Ingress
  ingress:
  - from:
    - namespaceSelector:
        matchLabels:
          kubernetes.io/metadata.name: monitoring
    ports:
    - protocol: TCP
      port: 10250  # kubelet metrics
    - protocol: TCP
      port: 6443   # API server metrics
    - protocol: TCP
      port: 10257  # controller manager metrics
    - protocol: TCP
      port: 10259  # scheduler metrics
```

### Сценарий 6: Защита от подов с hostNetwork

Поды с `hostNetwork: true` не фильтруются стандартной NetworkPolicy. Для защиты control plane от таких подов используйте hostEndpoint (Calico):

```yaml
# HostEndpoint для master-узла
apiVersion: projectcalico.org/v3
kind: HostEndpoint
metadata:
  name: master-1-eth0
  labels:
    node: master-1
    role: master
spec:
  node: master-1
  interfaceName: eth0
  expectedIPs:
  - 10.0.0.10
---
# GlobalNetworkPolicy: разрешить доступ к API Server только с разрешенных IP
apiVersion: projectcalico.org/v3
kind: GlobalNetworkPolicy
metadata:
  name: allow-apiserver-access
spec:
  order: 100
  selector: "node == 'master-1'"
  types:
  - Ingress
  ingress:
  # Разрешить от подов с правильными метками
  - action: Allow
    protocol: TCP
    destination:
      ports: [6443]
    source:
      nets: ["10.0.0.0/8"]
  # Разрешить etcd от API Server
  - action: Allow
    protocol: TCP
    destination:
      ports: [2379, 2380]
    source:
      nets: ["10.0.0.10/32"]
```

## Дополнительная информация

### Типичные ошибки

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `kubectl` не может подключиться к API Server | NetworkPolicy блокирует порт 6443 | Добавить Ingress-правило для IP рабочей станции |
| etcd timeout в логах API Server | NetworkPolicy блокирует etcd | Разрешить трафик от API Server к etcd (2379, 2380) |
| kubelet не отправляет метрики | NetworkPolicy блокирует scrape | Разрешить Ingress от Prometheus к порту 10250 |
| `connection refused` от API Server | API Server не слушает (-crash) | Проверить логи API Server, не NetworkPolicy |
| Scheduler не планирует поды | NetworkPolicy блокирует Scheduler → API Server | Разрешить Egress от Scheduler к API Server (6443) |

### Рекомендации по безопасности

| Компонент | Рекомендация |
| :--- | :--- |
| **etcd** | Никогда не размещайте в общем namespace с приложениями. Используйте отдельный namespace или firewall на уровне узла. |
| **API Server** | Разрешайте Ingress от CIDR узлов кластера и подов. Не используйте `0.0.0.0/0`. |
| **Controller Manager** | Не требует inbound. Блокируйте весь входящий трафик. |
| **Scheduler** | Аналогично Controller Manager. |
| **kubelet** | Разрешайте только от API Server. Monitoring можно через отдельное правило. |

### Чек-лист безопасности Control Plane

| # | Действие | Приоритет |
| :--- | :--- | :--- |
| 1 | Ограничить доступ к etcd (только API Server) | Критический |
| 2 | Настроить NetworkPolicy для API Server (не `0.0.0.0/0`) | Критический |
| 3 | Заблокировать inbound к Controller Manager и Scheduler | Высокий |
| 4 | Ограничить доступ к kubelet (только API Server) | Высокий |
| 5 | Настроить Default Deny для kube-system | Средний |
| 6 | Разрешить monitoring доступ к метрикам | Средний |
| 7 | Использовать hostEndpoint для master-узлов (Calico) | Средний |

### См. также

* [NetworkPolicy: Определения и концепции](./definitions.md) — базовые термины
* [NetworkPolicy: Лучшие практики](./best_practices.md) — рекомендации
* [etcd: Обзор](../../../Concepts/etcd_overview.md) — архитектура etcd
* [kube-proxy: Сетевой прокси](../kube-proxy.md) — DNAT и балансировка
