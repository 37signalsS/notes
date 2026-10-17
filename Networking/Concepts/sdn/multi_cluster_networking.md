## Определения

- **Multi-cluster Kubernetes**: Архитектура, при которой приложения работают в нескольких независимых Kubernetes кластерах. Каждый кластер имеет свой control plane, но сервисы могут быть federation-ные (доступные из других кластеров).
- **Cluster Mesh**: Технология Cilium, позволяющая подам из разных Kubernetes кластеров общаться напрямую (L3 connectivity) через overlay network. Поддерживает shared services (Service доступен из всех кластеров).
- **Kubernetes Federation (KubeFed)**: Рамочный API для управления несколькими Kubernetes кластерами как одним. Позволяет деплоить resources (Deployments, Services) across clusters. Deprecated в пользу Cluster API.
- **Cluster API (CAPI)**: Инструмент от Kubernetes SIG для управления жизненным циклом кластеров (provisioning, upgrading, scaling). Поддерживает providers: AWS, Azure, GCP, vSphere, bare-metal.
- **Service Mesh Federation**: Объединение нескольких service mesh (Istio, Linkerd) в один logical mesh. Позволяет service-to-service communication across clusters.
- **Cilium Cluster Mesh**: Позволяет共享 Kubernetes Services между кластерами. Поддерживает global services (any pod в any cluster может быть backend).
- **Multi-cluster Gateway**: Точка входа для external traffic в multi-cluster среде. Маршрутизирует трафик к правильному кластеру和服务.
- **Submariner**: CNCF проект для обеспечения L3 connectivity между Kubernetes кластерами (overlay network). Используется для multi-cluster service discovery.
- **Liqo**: Инструмент для peer-to-peer multi-cluster networking. Создает virtual cluster из нескольких physical clusters.
- **Admiralty**: Multi-cluster orchestration platform. Позволяет dispatch pods across clusters based on resource availability.

---

## Основные концепции

### Модели multi-cluster networking

| Модель | Описание | Продукты | Когда использовать |
| :--- | :--- | :--- | :--- |
| **Cluster Mesh (eBPF)** | L3 connectivity через eBPF. Shared services. | Cilium Cluster Mesh | High performance, eBPF-based networking |
| **Service Mesh Federation** | L7 connectivity через sidecar proxies. | Istio multi-cluster, Linkerd | Application-level routing, mTLS across clusters |
| **Submariner** | L3 connectivity через IPsec/WireGuard tunnels. | Submariner | Multi-cluster without CNI changes |
| **Cluster API** | Cluster lifecycle management (not networking). | CAPI + providers | Provisioning and management |
| **KubeFed** | Resource federation across clusters. | KubeFed (deprecated) | Legacy multi-cluster deployments |

### Cilium Cluster Mesh vs Istio Multi-cluster

| Критерий | Cilium Cluster Mesh | Istio Multi-cluster |
| :--- | :--- | :--- |
| **Уровень** | L3 (IP routing) | L7 (HTTP/gRPC routing) |
| **Transport** | eBPF (kernel) | Envoy sidecar (Userspace) |
| **Performance** | Высокая (~14Mpps) | Средняя (~1Mpps) |
| **Service discovery** | Kubernetes Service API | Istio ServiceEntry |
| **mTLS** | WireGuard (transparent) | Istio Citadel (sidecar) |
| **Shared services** | Да (global services) | Да (multi-cluster services) |
| **NetworkPolicy** | Да (global NetworkPolicy) | Да (Istio AuthorizationPolicy) |
| **Complexity** | Средняя | Высокая |
| **Назначение** | High-perf overlay networking | Application-level traffic management |

### Архитектура Cilium Cluster Mesh

```
Cluster A (K8s)                    Cluster B (K8s)
┌──────────────────────┐          ┌──────────────────────┐
│ Control Plane        │          │ Control Plane        │
│   API Server         │          │   API Server         │
│   etcd               │          │   etcd               │
├──────────────────────┤          ├──────────────────────┤
│ Cilium Agent (eBPF)  │          │ Cilium Agent (eBPF)  │
│   → VXLAN tunnels    │◄────────►│   → VXLAN tunnels    │
│   → BGP peering      │  IPsec   │   → BGP peering      │
│   → Cluster Mesh     │  tunnel  │   → Cluster Mesh     │
├──────────────────────┤          ├──────────────────────┤
│ Pods                 │          │ Pods                 │
│   Service A (local)  │          │   Service A (shared) │
│   Service B (local)  │          │   Service C (local)  │
└──────────────────────┘          └──────────────────────┘
         │                                   │
         └──── Shared Service A ─────────────┘
               (available in both clusters)
```

### Multi-cluster Service Discovery

| Service Type | Описание | Пример |
| :--- | :--- | :--- |
| **Local Service** | Service доступен только в своём кластере | `Service A` (Cluster A) |
| **Global Service** | Service доступен из всех кластеров | `Service B` (shared,Cluster A + B) |
| **Headless Service** | Pod-level DNS (без ClusterIP) | `StatefulSet` (shared) |
| **ExternalName** | CNAME-запись на внешний сервис | `Service C` (external) |

**Пример Global Service в Cilium Cluster Mesh:**
```yaml
# Service с global label (доступен из всех кластеров)
apiVersion: v1
kind: Service
metadata:
  name: backend
  labels:
    name: backend
    io.cilium/global: "true"    # ← Global service
spec:
  selector:
    app: backend
  ports:
  - port: 80
```

---

## Практические сценарии

### Сценарий 1: Cilium Cluster Mesh (2 clusters)

```bash
# 1. Подготовка clusters (оба кластера должны иметь Cilium)
# Кластер A:
export CLUSTER_A_NAME="cluster-a"
export CLUSTER_A_CTX="kind-cluster-a"
export CLUSTER_B_NAME="cluster-b"
export CLUSTER_B_CTX="kind-cluster-b"

# 2. Включение Cluster Mesh на обоих кластерах
cilium mesh enable --cluster $CLUSTER_A_NAME --cluster $CLUSTER_B_NAME

# 3. Проверка
cilium mesh status
# → Cluster Mesh Status
# →   cluster-a → cluster-b: OK (1 peer, 2 shared services)
# →   cluster-b → cluster-a: OK (1 peer, 1 shared service)

# 4. Доступ к shared service из cluster-b
kubectl --context $CLUSTER_B_CTX run test-client --image=curlimages/curl --rm -it -- \
    curl http://backend.mesh.cluster-a.local
# → Ответ от backend pod в cluster-a
```

### Сценарий 2: Istio multi-cluster (primary-remote)

```bash
# 1. Установка Istio на primary cluster (Cluster A)
istioctl install --set profile=default \
    --set meshConfig.enableAutoMtls=true \
    --set values.global.meshID=mesh1 \
    --set values.global.multiCluster.clusterName=cluster-a \
    --set values.global.network=network1

# 2. Установка Istio на remote cluster (Cluster B)
istioctl install --set profile=remote \
    --set values.global.meshID=mesh1 \
    --set values.global.multiCluster.clusterName=cluster-b \
    --set values.global.network=network2

# 3. Настройка shared services
kubectl apply -f - <<EOF
  apiVersion: networking.istio.io/v1
  kind: ServiceEntry
metadata:
  name: backend-cluster-b
  namespace: production
spec:
  hosts:
  - backend.production.svc.cluster.local
  location: MESH_INTERNAL
  ports:
  - number: 80
    name: http
    protocol: HTTP
  resolution: DNS
  addresses:
  - 240.0.0.10  # Virtual IP for multi-cluster
  endpoints:
  - address: backend-pod.cluster-b.local
    ports:
      http: 80
EOF

# 4. Проверка connectivity
istioctl x describe pod <pod-name>
# → Pod: production/backend-xxx
# →   Service: backend.production.svc.cluster.local
# →   DestinationRules: OK
# →   PeerAuthentication: OK (mTLS)
# →   Cross-cluster: available from cluster-b
```

### Сценарий 3: Submariner для L3 connectivity

```bash
# 1. Установка Submariner на broker cluster
subctl deploy-broker

# 2. Установка Submariner на каждом кластере
subctl join broker-info.subm --clusterid cluster-a
subctl join broker-info.subm --clusterid cluster-b

# 3. Проверка network connectivity
subctl show connections
# → Cluster: cluster-a → cluster-b: Connected (IPsec)
# →   Endpoints: 10.0.0.1 (cluster-a), 10.0.1.1 (cluster-b)

# 4. Просмотр service discovery
subctl show serviceimports
# → Service: backend.production (cluster-a) → import from cluster-b
```

---

## Диагностика и устранение неполадок

### Частые проблемы

| Проблема | Симптомы | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **Cluster Mesh not forming** | Cilium mesh status: no peers | `cilium mesh status` - no connections | Проверить network connectivity between clusters; проверить certificates; проверить ClusterID unique |
| **Shared service not reachable** | DNS resolution fails for global service | `nslookup backend.mesh.cluster.local` - NXDOMAIN | Проверить Cilium Cluster Mesh DNS configuration; проверить service labels |
| **Cross-cluster latency high** | Slow application response across clusters | `mtr <pod-ip>` - high RTT | Ensure direct connectivity (no backhauling); optimize overlay (VXLAN vs native routing) |
| **Service mesh federation not working** | Istio services not communicating | `istioctl analyze` - errors | Check mTLS certificates; verify ServiceEntry configuration; check network policies |
| **DNS resolution slow** | High DNS latency in multi-cluster | `dig backend.cluster.local` - slow | Enable Cilium DNS proxy; optimize CoreDNS configuration |

### Команды отладки

```bash
# Cilium Cluster Mesh
cilium mesh status                   # Cluster Mesh status
cilium mesh get-remote-clusters      # Remote cluster list
cilium bpf ct list global            # Cross-cluster connections

# Istio multi-cluster
istioctl analyze                     # Configuration analysis
istioctl x describe pod <pod>        # Pod connectivity status
istioctl proxy-status                # Sidecar proxy status
kubectl get serviceregistry -o yaml  # Service registry

# General multi-cluster
kubectl get endpoints -A             # Service endpoints across clusters
kubectl logs -n kube-system <cilium-pod>  # Cilium agent logs
```

---

## Дополнительная информация

**Производственные рекомендации:**
- Начинайте с Cilium Cluster Mesh (eBPF) для high-perf networking.
- Используйте Istio multi-cluster для application-level traffic management.
- Для simple L3 connectivity используйте Submariner (без CNI changes).
- Избегайте KubeFed (deprecated) - используйте Cluster API.

---

## Multi-cluster Gateway API

### Концепция

Gateway API поддерживает мультикластерные сценарии через несколько механизмов:

1. **Multi-cluster Gateway:** Единый Gateway, маршрутизирующий трафик к сервисам в разных кластерах.
2. **GAMMA (Gateway API for Mesh Management):** Управление East-West трафиком внутри и между кластерами.
3. **Multi-Cluster Service (MCS) API:** Стандарт Kubernetes для cross-cluster service discovery через `ServiceImport`/`ServiceExport`.

### Архитектура multi-cluster Gateway API

```
┌─────────────────┐    ┌─────────────────┐
│   Cluster A     │    │   Cluster B     │
│  ┌───────────┐  │    │  ┌───────────┐  │
│  │ Gateway   │◄─┼────┼──┤ Gateway   │  │
│  │ (Primary) │  │    │  │ (Secondary)│  │
│  └─────┬─────┘  │    │  └─────┬─────┘  │
│        │        │    │        │        │
│  ┌─────▼─────┐  │    │  ┌─────▼─────┐  │
│  │ Services  │  │    │  │ Services  │  │
│  └───────────┘  │    │  └───────────┘  │
└─────────────────┘    └─────────────────┘
        ▲                      ▲
        │                      │
   ┌────┴──────────────────────┴────┐
   │     Multi-Cluster Gateway      │
   │   (Единая точка входа)         │
   └────────────────────────────────┘
```

### Настройка Multi-Cluster Gateway (Envoy Gateway + KubeFed)

**Gateway в primary кластере:**
```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: multi-cluster-gw
  namespace: gateway-system
spec:
  gatewayClassName: envoy
  listeners:
  - name: https
    protocol: HTTPS
    port: 443
    tls:
      mode: Terminate
      certificateRefs:
      - name: wildcard-cert
    allowedRoutes:
      namespaces:
        from: Selector
        selector:
          matchLabels:
            kubernetes.io/metadata.name: production
```

**HTTPRoute с cross-cluster backendRefs:**
```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: app-route
  namespace: production
spec:
  parentRefs:
  - name: multi-cluster-gw
    namespace: gateway-system
  hostnames:
  - "app.example.com"
  rules:
  - backendRefs:
    - name: app-service
      namespace: production
      port: 8080
      weight: 80
    # Бэкенд из другого кластера (через MCS API)
    - name: app-service-cluster-b
      namespace: production
      port: 8080
      weight: 20
```

### Multi-Cluster Service (MCS) API

```yaml
# ServiceExport: помечает сервис как доступный из других кластеров
apiVersion: multicluster.x-k8s.io/v1alpha1
kind: ServiceExport
metadata:
  name: app-service
  namespace: production

---
# ServiceImport: импортирует сервис из другого кластера
apiVersion: multicluster.x-k8s.io/v1alpha1
kind: ServiceImport
metadata:
  name: app-service
  namespace: production
spec:
  type: ClusterSetIP
  ports:
  - port: 8080
    protocol: TCP
```

### Сравнение подходов

| Подход | Описание | Когда использовать |
|:---|:---|:---|
| **Multi-cluster Gateway** | Единый Gateway, весовая маршрутизация | Простые сценарии, fewer clusters |
| **GAMMA + Service Mesh** | East-West трафик через HTTPRoute | Микросервисы, mTLS между кластерами |
| **MCS API** | Стандарт Kubernetes service discovery | Стандартизированный подход,many clusters |

**Связанные темы:**
- **[Kubernetes CNI](./kubernetes_cni.md)** — CNI plugins для multi-cluster.
- **[Cilium](./ebpf_xdp.md)** — Cilium Cluster Mesh.
- **[Service Mesh](./sdn_overview.md#service-меш-как-расширение-sdn)** — Istio multi-cluster.
- **[SD-WAN](./sd_wan.md)** — multi-site connectivity.
- **[BGP EVPN](./bgp_evpn.md)** — multi-site DC fabrics.
- **[Gateway API](../../Kubernetes/Networking/gateway_api/definitions.md)** — базовые концепции Gateway API.
