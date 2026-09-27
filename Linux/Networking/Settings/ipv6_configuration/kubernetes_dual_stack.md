# Kubernetes Dual-Stack (IPv4/IPv6)

## Определения

**Dual-Stack** — режим работы Kubernetes-кластера, при котором Pod'ы и Service'ы получают адреса обоих стеков (IPv4 и IPv6) одновременно. Поддерживается начиная с Kubernetes 1.16 (alpha), стабильно — с 1.23.

**ipFamilyPolicy** — политика назначения семейства адресов в Service. Определяет, будет ли Service использовать один или оба стека: `SingleStack` (по умолчанию), `PreferDualStack` или `RequireDualStack`.

**ClusterCIDR** — диапазон Pod-адресов, выделяемых каждому узлу через `kube-controller-manager`. В Dual-Stack-кластере указываются два CIDR (один для IPv4, один для IPv6).

**CNI (Container Network Interface)** — плагин сетевого уровня, обеспечивающий маршрутизацию Pod-трафика. Не все CNI поддерживают Dual-Stack: Calico, Cilium и Canal — поддерживают; Flannel — с ограничениями.

## Основные концепции

### Требования к Dual-Stack

| Компонент | Минимальная версия | Особенности |
| :--- | :--- | :--- |
| **Kubernetes** | 1.23+ (GA) | `--feature-gates=IPv6DualStack=false` отключен по умолчанию |
| **CNI** | Зависит от плагина | Calico 3.14+, Cilium 1.10+, Canal 3.17+ |
| **kube-proxy** | 1.23+ | IPVS или iptables — оба поддерживают Dual-Stack |
| **DNS** | CoreDNS 1.8+ | Два A/AAAA-записи для Service |
| **Узлы** | Ядро Linux 4.x+ | IPv6 forwarding включен |

### Архитектура Dual-Stack

```
┌─────────────────────────────────────────────┐
│                API Server                    │
│  serviceClusterIPs: [10.96.0.0/16, fd00::/108] │
│  podSubnets: [10.244.0.0/16, fd01::/64]     │
└──────────────┬──────────────────────────────┘
               │
    ┌──────────┴──────────┐
    │                     │
┌───┴────────────┐  ┌────┴───────────┐
│    Node 1       │  │    Node 2       │
│ podCIDR:        │  │ podCIDR:        │
│ 10.244.1.0/24  │  │ 10.244.2.0/24  │
│ fd01:1::/80    │  │ fd01:2::/80    │
│                │  │                │
│ ┌─────┐        │  │ ┌─────┐        │
│ │Pod A│        │  │ │Pod C│        │
│ │v4+v6│        │  │ │v4+v6│        │
│ └─────┘        │  │ └─────┘        │
└────────────────┘  └────────────────┘
```

### Порядок назначения адресов Pod'ам

1. kubelet запрашивает Pod-адрес у CNI (через `CmdAdd`).
2. CNI выделяет по одному адресу из каждого `clusterCIDR` (IPv4 и IPv6).
3. Pod получает два IP-адреса в своём network namespace.
4. kube-proxy регистрирует оба адреса в Endpoints/EndpointSlice.
5. CoreDNS создаёт A и AAAA-записи для Service (оба стека).

### Family Policy в Service

| Политика | Поведение | Пример |
| :--- | :--- | :--- |
| **SingleStack** | Только один стек (по умолчанию). IPv6, если `clusterIPs` содержит `IPv6`, иначе IPv4. | `kubectl expose pod web --port=80` |
| **PreferDualStack** | Dual-Stack, если доступны оба стека. Fallback на SingleStack при ошибке. | `ipFamilyPolicy: PreferDualStack` |
| **RequireDualStack** | Требует оба стека. Service не будет создан, если один из CIDR недоступен. | `ipFamilyPolicy: RequireDualStack` |

### Dual-Stack vs IPv6-only

| Режим | Когда использовать | Ограничения |
| :--- | :--- | :--- |
| **Dual-Stack** | Миграция с IPv4, совместимость с legacy-приложениями | Двойное потребление ресурсов (два CIDR), сложность CNI |
| **IPv6-only** | Новые кластеры, mobile/edge, операторские сети | Требует DNS64/NAT64 для доступа к IPv4-ресурсам |

## Практические сценарии

### 1. Настройка кластера (kubeadm)

**kubeadm-конфигурация (`kubeadm-config.yaml`):**

```yaml
apiVersion: kubeadm.k8s.io/v1beta3
kind: ClusterConfiguration
kubernetesVersion: v1.29.0
networking:
  podSubnet: "10.244.0.0/16,fd01::/64"
  serviceSubnet: "10.96.0.0/16,fd00::/108"
  dnsDomain: "cluster.local"
controllerManager:
  extraArgs:
    allocate-node-cidrs: "true"
    cluster-cidr: "10.244.0.0/16,fd01::/64"
---
apiVersion: kubeadm.k8s.io/v1beta3
kind: InitConfiguration
nodeRegistration:
  kubeletExtraArgs:
    node-ip: "10.0.1.10,fd00::10"
```

**Настройка на worker-ноде (`kubeadm-join.yaml`):**

```yaml
apiVersion: kubeadm.k8s.io/v1beta3
kind: JoinConfiguration
discovery:
  bootstrapToken:
    apiServerEndpoint: "10.0.1.1:6443"
    token: "abc123."
    caCertHashes:
      - "sha256:..."
nodeRegistration:
  kubeletExtraArgs:
    node-ip: "10.0.1.11,fd00::11"
```

**Проверка после инициализации:**

```bash
# Проверка Pod-подсетей
kubectl get nodes -o wide
# → INTERNAL-IP   ...   10.0.1.10,fd00::10

# Проверка serviceSubnet
kubectl get svc -A | grep CLUSTER-IP
# → kubernetes   ClusterIP   10.96.0.1,fd00::1   443/TCP
```

### 2. CNI-конфигурация

#### Calico

```bash
# Установка Calico с Dual-Stack
kubectl apply -f https://raw.githubusercontent.com/projectcalico/calico/v3.27.0/manifests/calico.yaml

# Настройка Pod-подсетей
kubectl patch ipam-config default --type merge -p '{
  "spec": {
    "blocks": [
      {"cidr": "10.244.0.0/16", "affinity": "default"},
      {"cidr": "fd01::/64", "affinity": "default"}
    ]
  }
}'

# Проверка
calicoctl ipam show
```

#### Cilium

```bash
# Установка Cilium с Dual-Stack
helm install cilium cilium/cilium --version 1.15.0 \
  --set kubeProxyReplacement=true \
  --set ipv4NativeRoutingCIDR="10.244.0.0/16" \
  --set ipv6NativeRoutingCIDR="fd01::/64" \
  --set enableIPv6=true \
  --set enableIPv4=true

# Проверка
cilium status --all-health
```

#### Flannel (с ограничениями)

```bash
# Flannel поддерживает Dual-Stack с backend VXLAN
kubectl apply -f https://raw.githubusercontent.com/flannel-io/flannel/master/Documentation/kube-flannel.yml

# Настройка IPv6 через ConfigMap
kubectl patch configmap kube-flannel-cfg -n kube-flannel --type merge -p '{
  "data": {
    "net-conf.json": "{
      \"Network\": \"10.244.0.0/16\",
      \"SubnetLen\": 24,
      \"Backend\": {\"Type\": \"vxlan\"},
      \"AdditionalNetworks\": [{\"Network\": \"fd01::/64\", \"SubnetLen\": 80}]
    }"
  }
}'
```

### 3. Dual-Stack Service

```yaml
# Service с Dual-Stack
apiVersion: v1
kind: Service
metadata:
  name: my-service
spec:
  ipFamilyPolicy: PreferDualStack
  selector:
    app: my-app
  ports:
    - port: 80
      targetPort: 8080
  type: ClusterIP
---
# Deployment
apiVersion: apps/v1
kind: Deployment
metadata:
  name: my-app
spec:
  replicas: 3
  selector:
    matchLabels:
      app: my-app
  template:
    metadata:
      labels:
        app: my-app
    spec:
      containers:
        - name: nginx
          image: nginx:1.25
          ports:
            - containerPort: 8080
```

**Проверка:**

```bash
kubectl get svc my-service
# → NAME         TYPE        CLUSTER-IP      EXTERNAL-IP   PORT(S)
# → my-service   ClusterIP   10.96.0.50,fd00::50   <none>        80/TCP

kubectl get endpoints my-service
# → NAME         ENDPOINTS                                        AGE
# → my-service   10.244.1.5:8080,fd01:1::5:8080,...              5m
```

### 4. IPv6-only кластер

```yaml
# kubeadm для IPv6-only
apiVersion: kubeadm.k8s.io/v1beta3
kind: ClusterConfiguration
networking:
  podSubnet: "fd01::/64"
  serviceSubnet: "fd00::/108"
  dnsDomain: "cluster.local"
```

**Требования:**
- DNS64 (CoreDNS с плагином `dns64`) для доступа к IPv4-ресурсам
- NAT64 (Jool или аналог) на шлюзе кластера
- Внешние репозитории образов доступны по IPv6

### 5. Отладка Dual-Stack

```bash
# Проверка Pod IP-адресов (оба стека)
kubectl get pod -o jsonpath='{.items[*].status.podIPs}'

# Проверка Node IP-адресов
kubectl get nodes -o jsonpath='{.items[*].status.addresses}'

# DNS-резолвинг Service (проверка A и AAAA)
kubectl run dns-test --image=busybox --rm -it -- nslookup my-service.default.svc.cluster.local
# → Name:      my-service.default.svc.cluster.local
# → Address 1: 10.96.0.50
# → Address 2: fd00::50

# Проверка маршрутизации Pod-to-Pod (IPv6)
kubectl exec <pod-name> -- ping6 -c 3 fd01:2::5

# Проверка iptables/ipvs правил
kubectl exec -n kube-system <kube-proxy-pod> -- ipvsadm -Ln | grep -A2 "fd00::"

# Логи CNI при ошибке назначения адреса
kubectl logs -n kube-system <calico-pod> -c calico-node | grep -i "failed to assign"
```

## Дополнительная информация

### Типичные ошибки

| Симптом | Вероятная причина | Решение |
| :--- | :--- | :--- |
| Pod получает только IPv4 | CNI не поддерживает Dual-Stack | Обновить CNI до поддерживаемой версии |
| Service не имеет IPv6 ClusterIP | `ipFamilyPolicy: SingleStack` (default) | Установить `PreferDualStack` или `RequireDualStack` |
| IPv6-трафик не маршрутизируется между Pod'ами | IPv6 forwarding отключен на ноде | `sysctl -w net.ipv6.conf.all.forwarding=1` |
| DNS не возвращает AAAA-запись | CoreDNS не настроен для Dual-Stack | Проверить конфигурацию CoreDNS, `cluster.local` должен иметь оба семейства |
| kube-proxy не создает IPVS-правила для IPv6 | kube-proxy не поддерживает Dual-Stack | Обновить Kubernetes до 1.23+ |
| CNI-плагин конфликтует с Dual-Stack | Несовместимая версия CNI | Использовать Calico 3.14+, Cilium 1.10+, Canal 3.17+ |

### Best Practices

1. **Калькуляция PodCIDR:** Для Dual-Stack выделяйте отдельные CIDR каждого стека. Для IPv6 используйте `/80` на ноду (из `/64` кластера), чтобы оставить место для маршрутизации.
2. **ServiceSubnet:** IPv6 ServiceSubnet обычно `/108` (для ~16 миллионов Service'ов). IPv4 — `/16` (65 536 Service'ов).
3. **CNI-выбор:** Для Dual-Stack рекомендуется Calico (BGP-based) или Cilium (eBPF). Flannel имеет ограничения с IPv6-маршрутизацией.
4. **DNS64/NAT64:** Для IPv6-only кластеров настройте DNS64 в CoreDNS и NAT64 на сетевом шлюзе для доступа к IPv4-ресурсам (Docker Hub, GitHub).
5. **Тестирование:** Перед продакшеном протестируйте Dual-Stack в minikube/kind с конфигурацией двух Pod-подсетей.
6. **IPv6-only Migration:** Начните с Dual-Stack, затем отключите IPv4, когда все приложения корректно работают по IPv6.

### См. также

- **[Настройка адресов IPv6](./address_configuration.md)** — SLAAC, DHCPv6, статика.
- **[Firewall для IPv6](./firewall.md)** — kubernetes-специфичные правила nftables.
- **[Туннелирование IPv6](./tunneling.md)** — WireGuard, GRE для connectivity между кластерами.
- **[CNI: IPAM](../../../../Kubernetes/Networking/Network/CNI/ipam.md)** — управление Pod-адресами.
- **[CNI: Cilium](../../../../Kubernetes/Networking/Network/CNI/cilium.md)** — eBPF CNI с Dual-Stack.
- **[CNI: Выбор и внешний доступ](../../../../Kubernetes/Networking/Network/CNI/selection_and_external_access.md)** — IPv6 Dual-Stack в CNI.
