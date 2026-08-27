## Определения

- **CNI (Container Network Interface)**: Спецификация (CNCF), определяющая интерфейс между сетевыми плагинами и контейнерными рантаймами (containerd, CRI-O). Описывает как выделить сетевой namespace для пода, настроить сеть и удалить её при завершении пода.
- **CNI Plugin**: Программа, реализующая CNI-спецификацию: выделение IP-адреса, настройка маршрутизации, применение сетевых политик. Каждый CNI-плагин имеет свой подход к виртуализации сети.
- **Overlay Network**: Виртуальная сеть поверх физической (underlay). Трафик инкапсулируется (VXLAN, Geneve, IP-in-IP) для маршрутизации между узлами без изменения физической топологии.
- **Underlay Network**: Физическая сеть, на которой работают узлы Kubernetes. Ожидает маршрутизацию между Pod CIDR'ами (через BGP, static routes или OSPF).
- **NetworkPolicy**: Объект Kubernetes (API `networking.k8s.io/v1`), определяющий правила фильтрации трафика для подов (Ingress/Egress). Каждый CNI-плагин реализует NetworkPolicy по-своему.
- **Service Mesh**: Слой управления сервисным трафиком (L7), работающий поверх CNI. Sidecar-прокси (Envoy) управляют маршрутизацией, retry, mTLS между подами.
- **Multi-tenancy**: Архитектурный подход, где несколько команд/проектов работают в одном кластере, изолированных через NetworkPolicy, namespace quotas и отдельные кластеры.

---

## Основные концепции

### Модели сетей в Kubernetes

| Модель | Описание | Примеры CNI |
| :--- | :--- | :--- |
| **Overlay** | VXLAN/Geneve инкапсуляция между узлами. Простая настройка, overhead 50-62 байт на пакет. | Flannel (VXLAN), Calico (VXLAN/IP-in-IP), Antrea (VXLAN/Geneve) |
| **No-overlay (native routing)** | Трафик маршрутизируется без инкапсуляции. Требует BGP/static routes в underlay. Нулевой overhead. | Calico (BGP), Cilium (BGP), kube-router |
| **eBPF-based** | eBPF-программы в ядре Linux替代传统的 iptables/netfilter. Высокая производительность, L7-aware. | Cilium, Calico eBPF mode |
| **Hybrid** | Комбинация overlay + eBPF или overlay + BGP. | Cilium (VXLAN + eBPF), Calico (VXLAN + BGP) |

### Сравнение CNI-плагинов

| Критерий | **Flannel** | **Calico** | **Cilium** | **Antrea** | **Weave Net** |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Data Plane** | VXLAN (kernel) | eBPF / iptables / Linux routing | eBPF (kernel) | OpenFlow (OVS) | VXLAN (Userspace) |
| **NetworkPolicy** | Нет (нет!) | Полная | Полная (L3-L7) | Полная (L3-L7) | Базовая (L3-L4) |
| **Overlay** | VXLAN | VXLAN, IP-in-IP, Geneve | VXLAN, Geneve | VXLAN, Geneve, STT | VXLAN (sleeve) |
| **BGP** | Нет | Да (full mesh route reflector) | Да (в Agent mode) | Нет | Нет |
| **Service Mesh** | Нет | Нет (нужен Istio/Linkerd) | Да (内置 Cilium Service Mesh) | Нет | Нет |
| **L7 Visibility** | Нет | Нет | Да (HTTP, gRPC, Kafka) | Ограниченная | Нет |
| **Encryption (WireGuard/IPsec)** | Нет | Да (WireGuard, IPsec) | Да (WireGuard) | Да (IPsec) | Нет |
| **Масштабируемость** | ~5K узлов | ~5K узлов (BGP) | ~5K узлов | ~2K узлов (OVS) | ~500 узлов |
| **Производительность** | Средняя | Высокая (BGP mode) | Очень высокая (eBPF) | Средняя (OVS) | Низкая (Userspace) |
| **Простота настройки** | Очень простая | Средняя | Средняя | Средняя | Простая |
| **Production-ready** | Да (legacy) | Да | Да | Да | Ограниченная |

### Критерии выбора CNI

```
Нужна NetworkPolicy?
├── Нет → Flannel (простой, без policy)
└── Да
    ├── Нужна L7 visibility / Service Mesh?
    │   └── Да → Cilium
    ├── Нужен BGP в underlay?
    │   └── Да → Calico (BGP mode) или Cilium (BGP mode)
    ├── Используется OpenStack/KVM с OVN?
    │   └── Да → Antrea
    └── Нет особых требований → Calico (ibenx) или Cilium
```

**Рекомендация 2026:**
- **Новые кластеры**: Cilium (eBPF, высокая производительность, L7, Service Mesh).
- **Legacy/migration**: Calico (стабильный, проверенный, BGP).
- **Простые среды**: Flannel (если NetworkPolicy не нужна).

### Модели виртуализации сети

| Подход | Механизм | Преимущество | Недостаток |
| :--- | :--- | :--- | :--- |
| **veth pair** | Два виртуальных интерфейса: один в namespace пода, другой в bridge/host | Простота, стандарт Linux | Overhead (context switch) |
| **macvlan** | Под directly на физический интерфейс (L2) | Минимальный overhead, максимальная скорость | Ограничения (один под на интерфейс) |
| **ipvlan** | Как macvlan, но L3 (без MAC-学习) | Работает в облаках (нет MAC learning) | Ограничения в L2-средах |
| **SR-IOV** | Физический NIC разделяется на VF (Virtual Functions) | Apparatная изоляция,线速 производительность | Требует поддержку NIC, сложная настройка |
| **DPDK** | Userspace forwarding (bypass kernel) | Максимальная производительность | Сложная интеграция,失去 kernel features |

### NetworkPolicy в разных CNI

**Пример: NetworkPolicy (Kubernetes standard)**
```yaml
# Разрешает ingress к pod-ам с label app=api только из namespace frontend
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-frontend-to-api
  namespace: production
spec:
  podSelector:
    matchLabels:
      app: api
  policyTypes:
  - Ingress
  ingress:
  - from:
    - namespaceSelector:
        matchLabels:
          name: frontend
    ports:
    - protocol: TCP
      port: 8080
```

**Поведение CNI без NetworkPolicy:**
| CNI | Default Policy (без NetworkPolicy) |
| :--- | :--- |
| Flannel | Allow all (нет поддержки NetworkPolicy) |
| Calico | Allow all (policy не aplicada) |
| Cilium | Allow all (policy не aplicada) |
| Antrea | Allow all (policy не aplicada) |

**Важно:** Без явной NetworkPolicy все поды в кластере могут общаться друг с другом (east-west traffic разрешен по умолчанию).

---

## Практические сценарии

### Сценарий 1: Установка Cilium (production-ready)

```bash
# 1. Добавление репозитория Helm
helm repo add cilium https://helm.cilium.io/
helm repo update

# 2. Определение values для production
cat > cilium-values.yaml << 'EOF'
# Режим замены kube-proxy (eBPF-based)
kubeProxyReplacement: strict

# Overlay (VXLAN) для простоты; BGP для production networks
tunnel: vxlan

# Включить encrypting (WireGuard)
encryption:
  enabled: true
  type: wireguard

# NetworkPolicy enforcement
policyEnforcementMode: always

# Hubble для наблюдаемости
hubble:
  enabled: true
  relay:
    enabled: true
  ui:
    enabled: true

# Мониторинг
prometheus:
  enabled: true
  serviceMonitor:
    enabled: true

# Масштабирование
operator:
  replicas: 2
  resources:
    requests:
      cpu: 500m
      memory: 512Mi
EOF

# 3. Установка
helm install cilium cilium/cilium \
    --namespace kube-system \
    --values cilium-values.yaml

# 4. Проверка
cilium status
# →    /¯¯\
# → /¯¯\  IP: 10.0.0.10
# → \__/  Cilium: OK
# →       Kubernetes: OK
# →       etcd: OK
# →       kube-proxy replacement: strict
# →       Cilium health: OK
# →       Hubble: OK

# 5. Проверка eBPF datapath
kubectl -n kube-system exec -it <cilium-pod> -- cilium bpf prog list
```

### Сценарий 2: Установка Calico (BGP mode)

```bash
# 1. Установка Calico operator
kubectl create -f https://raw.githubusercontent.com/projectcalico/calico/v3.27.0/manifests/tigera-operator.yaml

# 2. Конфигурация Calico
cat <<EOF | kubectl apply -f -
apiVersion: operator.tigera.io/v1
kind: Installation
metadata:
  name: default
spec:
  calicoNetwork:
    ipPools:
    - blockSize: 26
      cidr: 10.244.0.0/16
      encapsulation: VXLANCrossSubnet  # VXLAN только между subnets
      natOutgoing: Enabled
      nodeSelector: all()
    nodeAddressAutodetectionV4:
      firstFound: true
  registry: quay.io/calico/
---
apiVersion: operator.tigera.io/v1
kind: APIServer
metadata:
  name: default
spec: {}
EOF

# 3. Настройка BGP (для full-mesh или route reflector)
cat <<EOF | kubectl apply -f -
apiVersion: projectcalico.org/v3
kind: BGPConfiguration
metadata:
  name: default
spec:
  logSeverityScreen: Info
  nodeToNodeMeshEnabled: true   # full-mesh (< 100 узлов)
  asNumber: 65100
  serviceClusterIPs:
  - cidr: 10.96.0.0/12
EOF

# 4. Проверка BGP peers
kubectl get pods -n calico-system
calicoctl node status
# → IPv4 BGP status
# → +---------------+-------------------+-------+----------+---------+
# → | PEER ADDRESS  |     PEER TYPE     | STATE |  SINCE   |  INFO   |
# → +---------------+-------------------+-------+----------+---------+
# → | 10.0.0.2      | node-to-node mesh | up    | 10:30:00 | Established |
# → | 10.0.0.3      | node-to-node mesh | up    | 10:30:00 | Established |
# → +---------------+-------------------+-------+----------+---------+

# 5. Создание GlobalNetworkPolicy
cat <<EOF | calicoctl create -f -
apiVersion: projectcalico.org/v3
kind: GlobalNetworkPolicy
metadata:
  name: deny-dns-external
spec:
  order: 100
  selector: app == 'dns'
  types:
  - Egress
  egress:
  - action: Allow
    protocol: UDP
    destination:
      ports:
      - 53
      selector: k8s-app == 'kube-dns'
  - action: Deny
    protocol: UDP
    destination:
      ports:
      - 53
EOF
```

### Сценарий 3: Сравнение производительности CNI

```bash
# Использование iperf3 для тестирования throughput между подами
# Установка iperf3
kubectl apply -f - <<EOF
apiVersion: apps/v1
kind: Deployment
metadata:
  name: iperf3-server
spec:
  replicas: 1
  selector:
    matchLabels:
      app: iperf3-server
  template:
    metadata:
      labels:
        app: iperf3-server
    spec:
      containers:
      - name: iperf3
        image: networkstatic/iperf3
        ports:
        - containerPort: 5201
        command: ["iperf3", "-s"]
---
apiVersion: v1
kind: Service
metadata:
  name: iperf3-server
spec:
  selector:
    app: iperf3-server
  ports:
  - port: 5201
EOF

# Запуск клиента (iperf3)
kubectl run iperf3-client --image=networkstatic/iperf3 --rm -it -- \
    iperf3 -c iperf3-server -t 30 -P 4

# Результаты для Cilium (eBPF, VXLAN):
# → [ ID] Interval       Transfer     Bitrate
# → [  5] 0.00-30.00  sec  34.5 GBytes  9.89 Gbits/sec

# Результаты для Calico (VXLAN):
# → [ ID] Interval       Transfer     Bitrate
# → [  5] 0.00-30.00  sec  31.2 GBytes  8.94 Gbits/sec

# Результаты для Flannel (VXLAN):
# → [ ID] Interval       Transfer     Bitrate
# → [  5] 0.00-30.00  sec  28.1 GBytes  8.05 Gbits/sec
```

### Сценарий 4: Multi-cluster networking (Cilium Cluster Mesh)

```bash
# Cluster Mesh позволяет подам из разных кластеров общаться напрямую
# Через Service discovery и shared services

# 1. Включить Cluster Mesh в обоих кластерах
cilium mesh enable --cluster cluster1 --cluster cluster2

# 2. Проверка
cilium mesh status
# → Cluster Mesh Status
# →   cluster1 → cluster2: OK (2 peers, 5 shared services)
# →   cluster2 → cluster1: OK (2 peers, 5 shared services)

# 3. Создание shared service (доступен из обоих кластеров)
kubectl apply -f - <<EOF
apiVersion: v1
kind: Service
metadata:
  name: backend
  labels:
    name: backend
    io.cilium/global: "true"       # Global service (shared across clusters)
spec:
  selector:
    app: backend
  ports:
  - port: 80
EOF

# 4. Доступ к shared service из другого кластера
kubectl run test-client --image=curlimages/curl --rm -it -- \
    curl http://backend.mesh.local
# → Ответ от backend pod в cluster2
```

---

## Диагностика и устранение неполадок

### Частые проблемы

| Проблема | Причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **Pod не получает IP** | CNI плагин не работает; insufficient IP addresses | `kubectl describe pod <pod>` → Events; `kubectl logs -n kube-system <cilium-pod>` | Проверить CIDR pool; проверить CNI конфиг (`/etc/cni/net.d/`) |
| **NetworkPolicy не работает** | CNI не поддерживает NetworkPolicy | `kubectl get networkpolicy` → check CNI capabilities | Переключиться на Calico/Cilium |
| **Service ClusterIP не маршрутизируется** | kube-proxy/ eBPF proxy не работает | `iptables -t nat -L KUBE-SERVICES`; `cilium bpf proxy list` | Перезапустить kube-proxy или включить eBPF mode |
| **DNS resolution fails** | CoreDNS not running; network isolation | `kubectl get pods -n kube-system -l k8s-app=kube-dns`; `nslookup kubernetes.default.svc.cluster.local` | Проверить CoreDNS; проверить NetworkPolicy (разрешить DNS egress) |
| **MTU mismatch** | Overlay добавляет overhead | `ping -M do -s 1472 <pod-ip>` | Уменьшить MTU на подах (Cilium: `bpf-mtu=1350`) |
| **High latency between pods** | Overlay overhead; node locality | `mtr <pod-ip>`; проверка cross-node traffic | Включить BGP mode (no overlay); использовать `topologyAwareHints` |

### Команды верификации

```bash
# Cilium
cilium status                          # Общее состояние
cilium bpf ct list global              # Connection tracking
cilium bpf policy list --endpoint ID   # Policy enforcement
cilium hubble observe                  # Network flow visualization

# Calico
calicoctl node status                  # BGP peers status
calicoctl get networkpolicy            # Network policies
calicoctl get bgpConfiguration         # BGP config

# Kubernetes
kubectl get pods -n kube-system -o wide  # Pods на конкретных нодах
kubectl describe node <node>             # Node conditions, pod CIDR
kubectl logs -n kube-system <cni-pod>   # CNI plugin logs
```

---

## Дополнительная информация

**Производственные рекомендации:**
- Всегда включайте NetworkPolicy в production (default deny all + allow needed traffic).
- Используйте BGP mode для крупных кластеров (>50 узлов) для снижения overhead.
- Для multi-cluster используйте Cluster Mesh (Cilium) или Federation API.
- Мониторьте eBPF maps (Cilium: `cilium bpf metrics list`) для обнаружения bottlenecks.

**Связанные темы:**
- **[eBPF/XDP](./ebpf_xdp.md)** — основа Cilium и современных CNI.
- **[Service Mesh](./sdn_overview.md#service-меш-как-расширение-sdn)** — L7 networking поверх CNI.
- **[Cilium (K8s)](../../Kubernetes/Networking/Network/CNI/cilium.md)** — полная документация Cilium.
- **[Calico (K8s)](../../Kubernetes/Networking/Network/CNI/calico.md)** — полная документация Calico.
- **[Overlay Networks](./vxlan_geneve.md)** — VXLAN/Geneve для overlay.
- **[SDN Overview](./sdn_overview.md)** — контекст архитектуры SDN.
