# Ошибки загрузки образов (Image Pull Errors): NetworkPolicy и доступ к реестру

## Определения

**NetworkPolicy** — объект Kubernetes, ограничивающий сетевое взаимодействие подов на L3/L4 уровне (IP, порты). Применяется к трафику **внутри пода** (ingress/egress). Не затрагивает pull-операции, выполняемые `kubelet` в host network namespace.

**Egress Policy** — часть NetworkPolicy, определяющая исходящие соединения пода. В контексте image pull — блокировка egress-трафика к реестру на уровне пода **не влияет** на загрузку образа, так как `kubelet` работает в host network namespace.

**Host Network Namespace** — сетевое пространство узла, в котором работает `kubelet` и CRI. Все pull-операции выполняются из этого пространства. NetworkPolicy пода не может повлиять на трафик host network namespace.

**GlobalNetworkPolicy** — политика CNI (Calico, Cilium), применяющаяся ко **всем** сетевым пространствам (включая host). В отличие от Kubernetes NetworkPolicy, может блокировать pull-трафик на уровне узла.

---

## Основные концепции

### Почему NetworkPolicy пода НЕ влияет на image pull

```
Pod Network Namespace              Host Network Namespace
┌─────────────────────┐            ┌──────────────────────────┐
│  Pod                 │            │  kubelet                 │
│  ┌──────────────┐   │            │  ┌────────────────────┐  │
│  │ containerd   │   │            │  │ containerd          │  │
│  │ (userns)     │   │            │  │ (host network)      │  │
│  └──────────────┘   │            │  └────────────────────┘  │
│                      │            │         │                │
│  NetworkPolicy ──────│────────────│──── × ──│─ (не работает) │
│  (применяется)       │            │         │                │
│                      │            │    pull to registry      │
│  ┌──────────────┐   │            │    (проходит)            │
│  │ app workload │   │            │                          │
│  └──────────────┘   │            └──────────────────────────┘
└─────────────────────┘
```

**Ключевой момент:** `kubelet` не участвует в сетевом взаимодействии с реестром напрямую. Он делает gRPC-вызов к CRI-плагину, который выполняет HTTP-запросы к реестру из host network namespace. Поэтому:

- NetworkPolicy пода **не может** блокировать pull
- NetworkPolicy пода **не может** разрешить pull, если он заблокирован на уровне host
- Только GlobalNetworkPolicy (Calico/Cilium) или правила `iptables`/`nftables` хоста влияют на pull

### Когда NetworkPolicy влияет на image pull (косвенно)

| Сценарий | Механизм | Симптом |
| :--- | :--- | :--- |
| **DNS-резолв через CoreDNS** | CoreDNS работает как под с NetworkPolicy. Если policy блокирует UDP/TCP 53 к CoreDNS — DNS-резолв на узле не работает | `dial tcp: lookup registry.example.com: no such host` |
| **Pull через Service ClusterIP** | Если приложение (init-container, sidecar) тянет образ через in-cluster registry (Harbor) по ClusterIP | `connection refused` / `no route to host` |
| **Mutating Webhook** | Webhook-сервер в кластере недоступен из-за NetworkPolicy | Pod creation timeout, image pull metadata丢失 |
| **imagePullSecrets из API** | kubelet обращается к API Server для получения секрета. Если сеть между kubelet и API нарушена — секрет не получен | `unauthorized: authentication required` |

### Практический чек-лист: что проверять при image pull + NetworkPolicy

| Шаг | Команда | Ожидаемый результат |
| :--- | :--- | :--- |
| 1 | `kubectl get networkpolicy -A` | Список всех политик в кластере |
| 2 | `kubectl describe networkpolicy <name>` | Проверить egress-правила: разрешены ли порты 443/80 к реестру |
| 3 | `kubectl exec -n <ns> <pod> -- curl -vI https://registry.example.com/v2/` | TCP + TLS end-to-end работает из пода |
| 4 | `kubectl exec -n <ns> <pod> -- nslookup registry.example.com` | DNS-резолв работает |
| 5 | `kubectl get cilliumnetworkpolicy -A` (если Cilium) | GlobalNetworkPolicy не блокирует egress к реестру |
| 6 | `kubectl get globalnetworkpolicy -A` (если Calico) | GlobalNetworkPolicy не блокирует egress к реестру |

---

## Практические сценарии

### Сценарий 1: DNS-резолв блокируется NetworkPolicy

**Симптом:** `dial tcp: lookup registry.example.com: no such host` на некоторых узлах. Pull работает на узлах без NetworkPolicy.

**Причина:** NetworkPolicy в namespace `kube-system` блокирует egress-трафик к CoreDNS Service.

**Диагностика:**
```bash
# Проверить NetworkPolicy в kube-system
kubectl get networkpolicy -n kube-system

# Проверить, есть ли egress-правила для CoreDNS
kubectl describe networkpolicy -n kube-system | grep -A 10 egress

# Тест DNS из пода
kubectl run dns-test --image=busybox --rm -it --restart=Never -- \
  nslookup registry.example.com
# → DNS resolution failed → проблема в NetworkPolicy
```

**Решение:**
```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-dns-egress
  namespace: kube-system
spec:
  podSelector: {}  # Все поды в namespace
  policyTypes:
    - Egress
  egress:
    - to: []  # Все назначения
      ports:
        - protocol: UDP
          port: 53
        - protocol: TCP
          port: 53
```

**Или глобальное разрешение DNS для всех подов:**
```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-dns-all-namespaces
  namespace: production
spec:
  podSelector: {}
  policyTypes:
    - Egress
  egress:
    - to: []  # Все назначения
      ports:
        - protocol: UDP
          port: 53
        - protocol: TCP
          port: 53
```

**Проверка после применения:**
```bash
kubectl apply -f allow-dns.yaml
kubectl exec -n production <pod> -- nslookup registry.example.com
# → registry.example.com -> 10.0.0.50   OK
```

### Сценарий 2: Pull через in-cluster registry (Harbor) с NetworkPolicy

**Симптом:** Init-container или sidecar пытается загрузить образ через in-cluster Harbor по ClusterIP. NetworkPolicy блокирует трафик к Service IP.

**Причина:** NetworkPolicy не разрешает egress к Service CIDR (10.96.0.0/12 по умолчанию).

**Диагностика:**
```bash
# Проверить ClusterIP Harbor
kubectl get svc harbor -n harbor
# → harbor    ClusterIP   10.96.50.20   443/TCP

# Проверить egress из пода
kubectl exec -n production <pod> -- curl -vI https://harbor.local:443/v2/
# → curl: (7) Failed to connect to harbor.local port 443: Connection refused

# Или через IP
kubectl exec -n production <pod> -- curl -vI https://10.96.50.20:443/v2/
# → curl: (28) Connection timed out
```

**Решение:**
```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-registry-egress
  namespace: production
spec:
  podSelector: {}
  policyTypes:
    - Egress
  egress:
    - to:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: harbor
      ports:
        - protocol: TCP
          port: 443
        - protocol: TCP
          port: 80
    - to: []  # DNS
      ports:
        - protocol: UDP
          port: 53
```

**Альтернатива (для init-контейнеров, которые тянут образы через Harbor):**
```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-harbor-init
  namespace: production
spec:
  podSelector: {}  # Или конкретный под
  policyTypes:
    - Egress
  egress:
    - to:
        - ipBlock:
            cidr: 10.96.50.0/24  # ClusterIP CIDR Harbor
      ports:
        - protocol: TCP
          port: 443
```

### Сценарий 3: Calico GlobalNetworkPolicy блокирует pull

**Симптом:** Pull работает на части узлов, на других — `connection timed out`. NetworkPolicy в кластере отсутствует, но Calico `GlobalNetworkPolicy` активна.

**Причина:** Calico `GlobalNetworkPolicy` применяется ко **всем** сетевым пространствам, включая host network namespace. В отличие от Kubernetes NetworkPolicy, она может блокировать pull-трафик.

**Диагностика:**
```bash
# Проверить GlobalNetworkPolicy
kubectl get globalnetworkpolicy

# Проверить egress-правила
kubectl describe globalnetworkpolicy <name> | grep -A 20 egress

# Проверить, есть ли разрешение к реестру
calicoctl get globalnetworkpolicy -o yaml | grep -A 10 "registry\|443\|80"
```

**Решение:**
```yaml
apiVersion: projectcalico.org/v3
kind: GlobalNetworkPolicy
metadata:
  name: allow-image-pull-egress
spec:
  selector: all()  # Ко всем подам
  types:
    - Egress
  egress:
    - action: Allow
      destination:
        ports:
          - 443
          - 80
      protocol: TCP
    - action: Allow
      destination:
        ports:
          - 53
      protocol: UDP
```

### Сценарий 4: Cilium ClusterNetworkPolicy блокирует pull

**Симптом:** Pull работает на узлах с Cilium, но на узлах без Cilium (или с другой версией CNI) — `connection timed out`.

**Причина:** Cilium `CiliumClusterwideNetworkPolicy` блокирует egress-трафик к реестру на узлах, где Cilium активен.

**Диагностика:**
```bash
# Проверить CiliumClusterwideNetworkPolicy
kubectl get ciliumclusterwidenetworkpolicy

# Проверить egress-правила
kubectl describe ciliumclusterwidenetworkpolicy <name> | grep -A 20 egress

# Проверить connectivity
cilium connectivity test --test pod-to-service
```

**Решение:**
```yaml
apiVersion: cilium.io/v2
kind: CiliumClusterwideNetworkPolicy
metadata:
  name: allow-registry-egress
spec:
  endpointSelector: {}  # Все поды
  egress:
    - toPorts:
        - ports:
            - port: "443"
              protocol: TCP
            - port: "80"
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

### Сценарий 5: imagePullSecrets и NetworkPolicy к API Server

**Симптом:** `unauthorized: authentication required` при pull. imagePullSecrets существуют и валидны, но kubelet не может получить их из-за NetworkPolicy.

**Причина:** kubelet обращается к API Server для получения secrets. Если NetworkPolicy блокирует трафик к API Server (или его VIP) — secret не получен.

**Диагностика:**
```bash
# Проверить, может ли kubelet достучаться до API
kubectl get node <node> -o jsonpath='{.status.addresses[?(@.type=="InternalIP")].address}'
# → 10.0.0.10

# Проверить доступность API с узла
ssh <node> "curl -k https://10.0.0.10:6443/api/v1/namespaces/production/secrets"
# → {"kind":"Status","apiVersion":"v1","metadata":{},"status":"Failure","message":"forbidden"} 
# Forbidden = OK (есть сеть, просто нет прав). Connection refused = проблема в NetworkPolicy.

# Проверить NetworkPolicy, блокирующий трафик к API
kubectl get networkpolicy -A | grep -i "api\|master\|control"
```

**Решение:**
```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-kubelet-to-api
  namespace: kube-system
spec:
  podSelector: {}  # Все поды в kube-system
  policyTypes:
    - Egress
  egress:
    - to:
        - ipBlock:
            cidr: 10.0.0.0/24  # CIDR control-plane
      ports:
        - protocol: TCP
          port: 6443
```

**Важно:** В production API Server обычно имеет выделенный VIP (например, `10.0.0.100`). Убедитесь, что NetworkPolicy разрешает egress к этому VIP.

---

## Дополнительная информация

### Связанные темы

- [Сетевые проблемы](./network_issues.md) — диагностика DNS, MTU и прокси (влияют на pull, но не связаны с NetworkPolicy).
- [Распространённые ошибки](./common_errors.md) — разбор ошибок реестров (401, 403, 429).
- [Лучшие практики](./best_practices.md) — рекомендации по стабильности и безопасности.
- [NetworkPolicy (теория)](../../../../Kubernetes/Networking/Network/NetworkPolicy/definitions.md) — полное описание NetworkPolicy, CNI и GlobalNetworkPolicy.
- [Cilium Network Policies](../../../../Kubernetes/Networking/Network/NetworkPolicy/cilium_network_policies.md) — специфика Cilium CNI.
- [Calico GlobalNetworkPolicy](../../../../Kubernetes/Networking/Network/NetworkPolicy/calico_global_network_policy.md) — специфика Calico CNI.
