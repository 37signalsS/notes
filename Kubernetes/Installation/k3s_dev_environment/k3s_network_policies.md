# NetworkPolicy в K3s: Calico и Cilium

Руководство по замене Flannel на Calico или Cilium в K3s для поддержки NetworkPolicy. Включает установку, конфигурацию, практические примеры политик и сравнение CNI.

Контекст: Встроенный Flannel в K3s НЕ поддерживает NetworkPolicy. Для production и собеседований необходимо уметь настраивать сетевые политики через Calico или Cilium. См. [Архитектура K3s](./k3s_architecture.md), [Управление ресурсами](./k3s_resource_management.md).

---

## Определения

| Термин | Описание |
| :--- | :--- |
| **NetworkPolicy** | Kubernetes API resource (`networking.k8s.io/v1`) для L3/L4 контроля доступа к подам. Работает по принципу allow-list: по умолчанию все разрешено, пока не определена политика. Требует CNI с поддержкой enforcement. |
| **Calico** | CNI-плагин, поддерживающий NetworkPolicy через iptables/nftables/eBPF. Включает BGP для маршрутизации, Felix (агент на ноде), Typha (fan-out proxy), GlobalNetworkPolicy. |
| **Cilium** | CNI-плагин на базе eBPF. Поддерживает NetworkPolicy L3/L4/L7, FQDN-фильтрацию, kube-proxy replacement, Hubble (наблюдаемость), Service Mesh (Ztunnel/Ambient Mode). |
| **Flannel** | CNI по умолчанию в K3s. Обеспечивает L3-связность через VXLAN, но НЕ поддерживает NetworkPolicy. |
| **eBPF** | Extended Berkeley Packet Filter — технология ядра Linux для программирования сетевого трафика на уровне XDP/TC. Позволяет Cilium выполнять policy enforcement без iptables. |
| **GlobalNetworkPolicy** | CRD Calico для определения политик на уровне кластера (не привязаны к namespace). |
| **CiliumNetworkPolicy** | CRD Cilium для расширенных политик: L7 (HTTP/gRPC), FQDN, entity-based. |

Навигация: [NetworkPolicy Definitions](../../Networking/Network/NetworkPolicy/definitions.md) | [Calico Guide](../../Security/network_policies/Calico/index.md) | [Cilium Guide](../../Networking/Network/CNI/cilium.md)

---

## Основные концепции

### Проблема Flannel в K3s

Flannel — простой CNI для L3-связности. Он НЕ реализует NetworkPolicy:

```yaml
# Эта политика БЕСПОЛЕЗНА с Flannel
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: deny-all
spec:
  podSelector: {}
  policyTypes:
    - Ingress
    - Egress
# С Flannel: все поды продолжают принимать/отправлять трафик
# С Calico/Cilium: входящий и исходящий трафик блокируется
```

### Сравнение CNI для K3s

| Критерий | Flannel | Calico | Cilium |
| :--- | :--- | :--- | :--- |
| **NetworkPolicy** | Нет | Да (L3/L4) | Да (L3/L4/L7) |
| **BGP** | Нет | Да | Да |
| **eBPF** | Нет | Опционально | Да (основа) |
| **kube-proxy replacement** | Нет | Опционально | Да |
| **FQDN filtering** | Нет | Нет | Да |
| **Service Mesh** | Нет | Нет | Да (Ztunnel) |
| **Наблюдаемость** | Нет | Нет | Hubble |
| **Сложность установки** | Низкая | Средняя | Средняя |
| **Нагрузка на CPU** | Минимальная | Низкая-Средняя | Средняя |
| **Для K3s dev** | Достаточно | Рекомендуется | Рекомендуется |

### Когда выбирать Calico vs Cilium

| Сценарий | Рекомендация |
| :--- | :--- |
| **Dev-окружение, простые политики** | Calico (проще настроить) |
| **L7-политики (HTTP/gRPC)** | Cilium |
| **FQDN-фильтрация** | Cilium |
| **Максимальная производительность** | Cilium (eBPF) |
| **Service Mesh без sidecar'ов** | Cilium (Ztunnel) |
| **Продакшен с BGP** | Calico или Cilium |

---

## Требования и предварительная подготовка

### Важно: отключение Flannel

Для установки Calico или Cilium необходимо отключить встроенный Flannel:

```bash
# При установке K3s:
curl -sfL https://get.k3s.io | INSTALL_K3S_EXEC="--disable-network-policy --flannel-backend=none" sh -

# ИЛИ добавить в /etc/rancher/k3s/config.yaml:
# disable-network-policy: true
# flannel-backend: none
```

**ВНИМАНИЕ:** Это отключает NetworkPolicy controller K3s. Calico или Cilium берут эту функцию на себя.

---

## Практические сценарии

### 1. Установка Calico через Helm

```bash
# Добавление репозитория
helm repo add projectcalico https://docs.tigera.io/calico/charts
helm repo update

# Установка Calico (operator mode)
helm install calico projectcalico/tigera-operator \
  --namespace tigera-operator \
  --create-namespace \
  --set installation.calicoNetwork.ipPools[0].blockSize=26 \
  --set installation.calicoNetwork.ipPools[0].cidr=10.42.0.0/16 \
  --set installation.calicoNetwork.ipPools[0].encapsulation=VXLANCrossSubnet \
  --set installation.calicoNetwork.ipPools[0].natOutgoing=true \
  --set installation.calicoNetwork.ipPools[0].nodeSelector=all()

# Ожидание готовности
kubectl get pods -n tigera-operator -w
# → NAME                                       READY   STATUS    AGE
# → tigera-operator-xxx                        1/1     Running   30s

# Проверка Calico-компонентов
kubectl get pods -n calico-system -w
# → NAME                                       READY   STATUS    AGE
# → calico-node-xxxxx                          1/1     Running   60s
# → calico-typha-xxxxxxxxxx-xxxxx              1/1     Running   60s

# Проверка Installation
kubectl get installation
# → NAME      AGE
# → default   60s

# Проверка IP Pool
kubectl get ippool
# → NAME         AGE
# → default-ipv4-ippool   60s
```

### 2. Установка Cilium через Helm

```bash
# Добавление репозитория
helm repo add cilium https://helm.cilium.io
helm repo update

# Установка Cilium (с kube-proxy replacement)
helm install cilium cilium/cilium \
  --namespace kube-system \
  --set kubeProxyReplacement=true \
  --set k8sServiceHost=<API_SERVER_IP> \
  --set k8sServicePort=6443 \
  --set hubble.enabled=true \
  --set hubble.relay.enabled=true \
  --set hubble.ui.enabled=true \
  --set operator.replicas=1

# Ожидание готовности
kubectl -n kube-system get pods -w | grep cilium
# → cilium-xxxxx                          1/1     Running   0          60s
# → cilium-operator-xxxxxxxxxx-xxxxx      1/1     Running   0          60s
# → hubble-relay-xxxxxxxxxx-xxxxx         1/1     Running   0          30s
# → hubble-ui-xxxxxxxxxx-xxxxx            2/2     Running   0          30s

# Проверка статуса Cilium
kubectl -n kube-system exec cilium-xxxxx -- cilium status
# →    /¯¯\
# → /¯¯\  _|  _/-\ _  |  Package:       cilium 1.16.1
# → \__/¯¯/,/¯¯'/    |  Kubernetes:    v1.36.3+k3s1
# →          --||__|  |  Cilium:        1.16.1
# →          /¯¯   \  |  Hubble:        enabled
# →        /    \   |  kube-proxy:     replaced
# →              \  |  CNI plugin:     cilium
# →               | |  Host routing:   eBPF
# →               | |  Masquerading:   eBPF
```

### 3. Базовые NetworkPolicy (работают с Calico и Cilium)

```yaml
# 1. Default Deny All (все поды в namespace изолированы)
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: default-deny-all
  namespace: dev-workspaces
spec:
  podSelector: {}
  policyTypes:
    - Ingress
    - Egress
```

```yaml
# 2. Разрешить DNS (КРИТИЧНО: без этого поды не смогут резолвить имена)
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-dns
  namespace: dev-workspaces
spec:
  podSelector: {}
  policyTypes:
    - Egress
  egress:
    - to: []
      ports:
        - protocol: UDP
          port: 53
        - protocol: TCP
          port: 53
```

```yaml
# 3. Разрешить SSH только из доверенной сети
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-ssh-trusted
  namespace: dev-workspaces
spec:
  podSelector:
    matchLabels:
      app: dev-container
  policyTypes:
    - Ingress
  ingress:
    - from:
        - ipBlock:
            cidr: 192.168.1.0/24
      ports:
        - protocol: TCP
          port: 22
```

```yaml
# 4. Разрешить GitLab -> Harbor (меж-namespace)
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-gitlab-to-harbor
  namespace: harbor
spec:
  podSelector:
    matchLabels:
      app: harbor-core
  policyTypes:
    - Ingress
  ingress:
    - from:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: gitlab
      ports:
        - protocol: TCP
          port: 443
```

### 4. Расширенные CiliumNetworkPolicy (L7)

```yaml
# CiliumNetworkPolicy: разрешить HTTP GET только для /api/*
apiVersion: cilium.io/v2
kind: CiliumNetworkPolicy
metadata:
  name: allow-http-api
  namespace: gitlab
spec:
  endpointSelector:
    matchLabels:
      app: webservice
  ingress:
    - fromEndpoints:
        - matchLabels:
            app: ingress-nginx
      toPorts:
        - ports:
            - port: "8181"
              protocol: TCP
          rules:
            http:
              - method: GET
                path: "/api/.*"
```

```yaml
# CiliumNetworkPolicy: FQDN filtering (разрешить доступ только к определенным доменам)
apiVersion: cilium.io/v2
kind: CiliumNetworkPolicy
metadata:
  name: allow-external-api
  namespace: dev-workspaces
spec:
  endpointSelector:
    matchLabels:
      app: dev-container
  egress:
    - toFQDNs:
        - matchName: "api.github.com"
        - matchName: "registry.npmjs.org"
      toPorts:
        - ports:
            - port: "443"
              protocol: TCP
    - toEndpoints:
        - matchLabels:
            k8s:io.kubernetes.pod.namespace: kube-system
            k8s-app: kube-dns
      toPorts:
        - ports:
            - port: "53"
              protocol: UDP
```

### 5. Проверка работы NetworkPolicy

```bash
# Проверка, что Calico/Cilium применяет политики
kubectl get networkpolicy -A
# → NAME              POD-SELECTOR   AGE
# → default-deny-all   <none>         5m
# → allow-dns          <none>         5m
# → allow-ssh-trusted  app=container  5m

# Тест: попытка подключения к поду с отклоненной политикой
kubectl -n dev-workspaces exec deploy/dev-container -- curl -s --connect-timeout 5 http://harbor.dev.local
# → Если NetworkPolicy работает: timeout (connection refused)

# Тест: DNS должен работать
kubectl -n dev-workspaces exec deploy/dev-container -- nslookup gitlab.dev.local
# → Server:    10.43.0.10
# → Name:      gitlab.dev.local
# → Address:   10.43.x.x
```

---

## Типичные ошибки и устранение неполадок

### Ошибка: NetworkPolicy не применяется (Flannel)

```bash
# Проверка CNI
kubectl get pods -n kube-system -l app=flannel
# → Если flannel запущен — NetworkPolicy не работает

# Проверка: установите Calico или Cilium (см. сценарии выше)
```

### Ошибка: DNS не работает после включения Default Deny

```bash
# Причина: забыли создать политику allow-dns
# Решение: немедленно создайте политику allow-dns (см. сценарий 3)
kubectl apply -f - <<EOF
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-dns
  namespace: dev-workspaces
spec:
  podSelector: {}
  policyTypes:
    - Egress
  egress:
    - to: []
      ports:
        - protocol: UDP
          port: 53
        - protocol: TCP
          port: 53
EOF
```

### Ошибка: Calico показывает `NotReady`

```bash
# Проверка логов calico-node
kubectl -n calico-system logs calico-node-xxxxx --tail=50
# → Ищите "failed to connect" или "BGP"

# Проверка BGP peering (для multi-node)
kubectl get bgpConfiguration
kubectl get bgppeer

# Для single-node: BGP не требуется, VXLAN sufficient
```

---

## Дополнительная информация

### CIS Benchmark и NetworkPolicy

Для соответствия CIS Kubernetes Benchmark требуются NetworkPolicy. Это критично для прохождения аудитов:

| CIS Benchmark | Требование | Решение |
| :--- | :--- | :--- |
| 5.3.2 | Ensure that all Namespaces have NetworkPolicy defined | Default Deny + allow-dns в каждом namespace |
| 5.7.1 | The default namespace should not be used | NetworkPolicy в default namespace |

### Предупреждения

| Аспект | Риск | Рекомендация |
| :--- | :--- | :--- |
| **Default Deny** | Блокирует DNS если не создать allow-dns | ВСЕГДА создавайте allow-dns первым |
| **Flannel** | Не поддерживает NetworkPolicy | Для dev можно оставить Flannel, для prod — Calico/Cilium |
| **Cilium eBPF** | Требует ядро 5.10+ | Проверьте `uname -r` перед установкой |
| **Calico Typha** | Нужен только для >50 нод | В dev-окружении не требуется |

### См. также

- [NetworkPolicy Definitions](../../Networking/Network/NetworkPolicy/definitions.md) -- общие концепции
- [Calico Guide](../../Security/network_policies/Calico/index.md) -- архитектура Calico
- [Cilium Guide](../../Networking/Network/CNI/cilium.md) -- eBPF и Cilium
- [DNS + NetworkPolicy](../../Networking/Network/NetworkPolicy/dns_network_policy.md) -- проблема DNS при Default Deny
- [Архитектура K3s](./k3s_architecture.md) -- CNI по умолчанию
