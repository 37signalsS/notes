# vCluster — сетевые особенности

> Документ описывает сетевую модель vCluster: как Pod внутри vCluster получает IP, DNS, маршрутизацию, Service Mesh, проблемные места. Связность — в [vcluster_connectivity.md](./vcluster_connectivity.md), безопасность — в [vcluster_security_and_sync.md](./vcluster_security_and_sync.md).

## Определения

**Virtual Network** — виртуальная сеть, создаваемая vCluster для подов внутри виртуального кластера. Поды получают IP из виртуального CIDR, маршрутизация идёт через Syncer.

**Service ClusterIP** — виртуальный IP сервиса внутри vCluster. Недоступен напрямую с хоста — только через Syncer.

**CoreDNS** — DNS-сервер внутри vCluster. Резолвит имена сервисов в формате `<svc>.<ns>.svc.cluster.local`.

**DNS Forwarding** — проброс DNS-запросов из vCluster наружу (в DNS хост-кластера или внешние DNS).

**CNI (Container Network Interface)** — плагин, реализующий сетевую модель подов. На хосте: Calico, Cilium, Flannel.

**Service Mesh** — инфраструктурный слой для управления трафиком между сервисами (Istio, Linkerd). В vCluster требует особых настроек.

**WireGuard** — современный VPN-протокол, используемый vCluster VPN для P2P-соединений.

**mTLS (Mutual TLS)** — TLS с двусторонней аутентификацией. Используется Service Mesh и может конфликтовать с vCluster API.

## Основные концепции

### Сетевая модель vCluster

```text
┌─────────────────────────────────────────────────────────────────┐
│                    Host Cluster Network                          │
│  CIDR: 10.244.0.0/16 (Pods), 10.96.0.0/12 (Services)          │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │ vCluster Namespace: team-alpha                               │ │
│  │                                                              │ │
│  │  ┌──────────────────────────────────────────────────────┐   │ │
│  │  │ Syncer Pod (10.244.1.5)                              │   │ │
│  │  │   └── port-forward: 8443 → API Server vCluster       │   │ │
│  │  └──────────────────────────────────────────────────────┘   │ │
│  │                                                              │ │
│  │  ┌──────────────────────────────────────────────────────┐   │ │
│  │  │ Tenant Pod (10.244.1.10)                             │   │ │
│  │  │   ├── IP из хост-CIDR (10.244.x.x)                  │   │ │
│  │  │   ├── DNS: 10.96.0.10 (CoreDNS vCluster)            │   │ │
│  │  │   └── Service: my-svc.team-alpha.svc.cluster.local   │   │ │
│  │  └──────────────────────────────────────────────────────┘   │ │
│  └─────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘

         │ Syncer маппит
         ▼
┌─────────────────────────────────────────────────────────────────┐
│  Inside vCluster (виртуальная сеть)                              │
│  CIDR: 10.96.0.0/12 (виртуальные Services)                     │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────────┐│
│  │ Tenant Pod (10.96.1.5) ← виртуальный IP                     ││
│  │   ├── DNS: 10.96.0.10 (CoreDNS vCluster)                   ││
│  │   └── Service: 10.96.0.100 (my-svc)                         ││
│  └──────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────┘
```

### Как Pod внутри vCluster получает IP

1. Pod создаётся внутри vCluster → API-сервер vCluster планирует его на "виртуальную ноду".
2. Syncer перехватывает Pod и создаёт "теневой" Pod в namespace хоста.
3. kubelet хоста выдаёт IP из CIDR хост-кластера (10.244.x.x).
4. Syncer патчит IP в статус Pod внутри vCluster (может оставлять виртуальный IP).

### DNS-архитектура

```text
Tenant Pod (внутри vCluster)
    │
    │ DNS query: my-svc.team-alpha.svc.cluster.local
    ▼
CoreDNS (внутри vCluster, 10.96.0.10)
    │
    ├─ Внутренний запрос → резолвит в виртуальном пространстве
    │   Ответ: 10.96.0.100
    │
    └─ Внешний запрос (corp.local, example.com)
        │
        ├─ forward plugin → DNS хост-кластера
        │   Ответ: 10.96.1.50 (внутренний DNS)
        │
        └─ stub-domains → внешние DNS
            Ответ: 8.8.8.8 (публичный DNS)
```

### Типы сервисов и их поведение в vCluster

| Тип Service | Внутри vCluster | На хосте | Доступность |
| :--- | :--- | :--- | :--- |
| **ClusterIP** | Виртуальный IP (10.96.x.x) | ClusterIP из хоста | Только внутри vCluster |
| **NodePort** | Виртуальный NodePort | Реальный NodePort | С хоста через NodePort |
| **LoadBalancer** | Виртуальный LB | Создаётся реальный LB (опционально) | Внешний доступ |
| **ExternalName** | CNAME | CNAME | Глобально |

### Проблема: ServiceMesh и mTLS

Service Mesh (Istio/Linkerd) использует sidecar-прокси для перехвата трафика. В vCluster это создаёт конфликты:

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| Sidecar не.injected | Namespace не помечен для injection | Добавить метку `istio-injection: enabled` в namespace vCluster на хосте |
| mTLS конфликт | Два CA (Istio + vCluster) | Использовать единый CA или отключить mTLS для vCluster API |
| Syncer не видит Envoy | Envoy не синхронизируется | Включить generic sync для CRD Istio |
| Latency > 50ms | Два прокси (Envoy + Syncer) | Оптимизировать, использовать fewer hops |

## Практические сценарии

### Настройка DNS forwarding

```yaml
# vcluster.yaml
controlPlane:
  distro:
    k8s:
      enabled: true
  coreDNS:
    configuration: |
      .:53 {
          errors
          health
          kubernetes cluster.local in-addr.arpa ip6.arpa {
            pods insecure
            fallthrough in-addr.arpa ip6.arpa
          }
          prometheus :9153
          forward . /etc/resolv.conf
          cache 30
          loop
          reload
          loadbalance
      }
      # Forward для внутренних доменов
      corp.local:53 {
          errors
          cache 30
          forward . 10.96.0.10  # DNS хост-кластера
      }
```

### Настройка NetworkPolicy для изоляции

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: vcluster-isolation
  namespace: team-alpha
spec:
  podSelector: {}
  policyTypes:
    - Ingress
    - Egress
  ingress:
    # Разрешить трафик только внутри vCluster
    - from:
        - podSelector: {}
    # Разрешить от Syncer
    - from:
        - namespaceSelector:
            matchLabels:
              vcluster.loft.sh/parent: team-alpha
      ports:
        - protocol: TCP
          port: 8443
  egress:
    # DNS
    - to:
        - namespaceSelector: {}
      ports:
        - protocol: UDP
          port: 53
        - protocol: TCP
          port: 53
    # Внутренние сервисы
    - to:
        - podSelector: {}
    # Блокировка всего остального
    - to:
        - ipBlock:
            cidr: 0.0.0.0/0
            except:
              - 10.0.0.0/8
              - 172.16.0.0/12
              - 192.168.0.0/16
```

### Интеграция с Istio

```yaml
# vcluster.yaml
controlPlane:
  distro:
    k8s:
      enabled: true
  # Включить синхронизацию CRD Istio
  sync:
    toHost:
      customResources:
        virtualservices.networking.istio.io:
          enabled: true
        destinationrules.networking.istio.io:
          enabled: true
        gateways.networking.istio.io:
          enabled: true
    fromHost:
      customResources:
        gateways.networking.istio.io:
          enabled: true
  # Настройка namespace для injection
  namespace: team-alpha
  labels:
    istio-injection: enabled
```

### Интеграция с Cilium

Cilium как CNI на хосте обеспечивает eBPF-маршрутизацию и network policy:

```yaml
# Настройка Cilium для vCluster
# cilium-values.yaml
cilium:
  enabled: true
  # Включить eBPF для service routing
  bpf:
    masquerade: true
  # Включить host routing
  hostRouting: true
  # Включить kube-proxy replacement
  kubeProxyReplacement: strict
  # Включить health checking
  healthChecking: true
```

### Отладка сетевых проблем

```bash
# 1. Проверить IP Pod внутри vCluster
vcluster connect <name> -n <ns> -- kubectl get pod -o wide
# → NAME    READY   STATUS    IP           NODE
# → nginx   1/1     Running   10.96.1.5    vcluster-node

# 2. Проверить IP Pod на хосте
kubectl -n <ns> get pods -l vcluster.loft.sh/managed-by -o wide
# → NAME                  READY   STATUS    IP            NODE
# → nginx-<vc>-xxx        1/1     Running   10.244.1.10   node-1

# 3. Проверить DNS
vcluster connect <name> -n <ns> -- nslookup kubernetes.default
# → Server: 10.96.0.10
# → Address 1: 10.96.0.10 kube-dns.kube-system.svc.cluster.local

# 4. Проверить connectivity
vcluster connect <name> -n <ns> -- curl -k https://kubernetes.default.svc/healthz
# → ok

# 5. Проверить NetworkPolicy
kubectl -n <ns> get networkpolicy
# → NAME                  POD-SELECTOR   AGE
# → vcluster-isolation    {}             5m

# 6. Проверить DNS forwarding
vcluster connect <name> -n <ns> -- nslookup corp.local
# → Server: 10.96.0.10
# → Name: corp.local
# → Address 1: 10.96.1.50

# 7. Проверить MTU
vcluster connect <name> -n <ns> -- ping -c 3 -M do -s 1472 kubernetes.default
# → PING kubernetes.default (10.96.0.1): 1472 data bytes
# → 1480 bytes from 10.96.0.1: icmp_seq=0 ttl=64 time=0.123 ms
```

### Диагностика сетевых проблем

| Симптом | Вероятная причина | Решение |
| :--- | :--- | :--- |
| DNS не резолвит | CoreDNS не запущен, forwarding не настроен | `kubectl -n <vc-ns> get pods -l k8s-app=kube-dns` |
| Service недоступен из vCluster | `sync.fromHost.services` отключён | Включить `sync.fromHost.services.enabled` |
| Pod не получает IP | CNI не работает на хосте | Проверить CNI pod, `kubectl -n kube-system get pods` |
| Медленный трафик (>100ms) | Дополнительный hop через Syncer | Использовать прямую маршрутизацию (VPN mode) |
| Connection refused | NetworkPolicy блокирует | Проверить NetworkPolicy, временно отключить |
| MTU mismatch, фрагментация | WireGuard/overlay добавляет заголовки | Снизить MTU до 1450 в vCluster |
| mTLS не работает | Два CA, конфликт сертификатов | Использовать единый CA, federation |

### Лучшие практики

- **DNS isolation — фича, не баг:** Не пробрасывайте весь DNS хоста. Forwarding только для конкретных доменов (`.corp.local`).
- **NetworkPolicy на хосте:** Убедитесь, что CNI поддерживает NetworkPolicy (Calico, Cilium). Kindnet/flannel не поддерживают.
- **MTU для overlay:** Если используете WireGuard/VXLAN, установите MTU 1450 внутри vCluster.
- **Service Mesh:** Istio в vCluster требует синхронизации CRD. Используйте generic sync.
- **Прямая маршрутизация:** Для latency-critical приложений используйте vCluster VPN (WireGuard) вместо port-forward.
- **Мониторинг DNS:** Алерт на `coredns_dns_request_count_total` рост > baseline.

## Дополнительная информация

### Внутренние ссылки

- [vCluster — подключение и доступ](./vcluster_connectivity.md)
- [vCluster — безопасность и синхронизация](./vcluster_security_and_sync.md)
- [vCluster — troubleshooting](./vcluster_troubleshooting.md)

### См. также

- [Gateway API — troubleshooting](../../Kubernetes/Networking/gateway_api/troubleshooting_deep_dive.md)
- [NetworkPolicy — GitOps CI/CD](../../Kubernetes/Networking/Network/NetworkPolicy/gitops_ci_cd.md)

### Внешние ссылки

- [vCluster Networking Documentation](https://www.vcluster.com/docs/architecture/networking)
- [Cilium Documentation](https://docs.cilium.io/)
- [Istio on Kubernetes](https://istio.io/latest/docs/setup/)
