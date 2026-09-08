# DNS и NetworkPolicy: Архитектура и Production-проблемы

## Определения

**CoreDNS** — стандартный DNS-сервер в Kubernetes, работающий как Deployment в `kube-system`. Обеспечивает разрешение имен сервисов (`<svc>.<ns>.svc.cluster.local`) и подов. Каждый под обращается к CoreDNS по фиксированному ClusterIP (обычно `10.96.0.10`).

**NodeLocal DNSCache (NLDC)** — DaemonSet, запускающий кэширующий DNS-агент на каждом узле. Работает на IP `169.254.20.10` (по умолчанию). Снижает нагрузку на CoreDNS, минимизирует задержки и решает проблемы с UDP conntrack race conditions.

**DNS Policy (dnsPolicy)** — параметр Pod Spec, определяющий способ формирования `/etc/resolv.conf`: `ClusterFirst` (по умолчанию), `Default`, `ClusterFirstWithHostNet`, `None`.

**Conntrack Race Condition** — проблема, возникающая при одновременном создании множества DNS-запросов через UDP. Ядро Linux может неправильно сопоставить ответы с запросами, что приводит к задержкам 1-5 секунд или ошибке `SERVFAIL`.

**ndots** — параметр в `/etc/resolv.conf`, определяющий, сколько точек должно быть в DNS-имени для прямого разрешения. По умолчанию `5` в Kubernetes, что вызывает 4 лишних DNS-запроса для внешних доменов.

## Базовые Концепции

### Архитектура DNS в Kubernetes

```
┌─────────────────────────────────────────────────────────┐
│ Узел (Node)                                              │
│ ┌─────────────────────────────────────────────────────┐  │
│ │ Pod                                                 │  │
│ │ /etc/resolv.conf → nameserver 169.254.20.10        │  │
│ │ (ndots:5)                                           │  │
│ └─────────────────────┬───────────────────────────────┘  │
│                       │ UDP 53                            │
│ ┌─────────────────────▼───────────────────────────────┐  │
│ │ NodeLocal DNSCache (DaemonSet)                      │  │
│ │ 169.254.20.10:53                                    │  │
│ │ ├── Кеш: есть → ответ                              │  │
│ │ └── Кеш: нет → forward в CoreDNS                   │  │
│ └─────────────────────┬───────────────────────────────┘  │
│                       │ TCP/UDP 53                        │
│ ┌─────────────────────▼───────────────────────────────┐  │
│ │ CoreDNS (Deployment в kube-system)                  │  │
│ │ 10.96.0.10:53                                       │  │
│ │ ├── Kubernetes plugin (Service/Pod разрешение)      │  │
│ │ ├── Cache plugin (кеш ответов)                     │  │
│ │ └── Forward plugin (upstream DNS)                   │  │
│ └─────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
```

### Проблема DNS при Default Deny Egress

При включении Egress Default Deny поды теряют доступ к DNS:

```yaml
# ВСЕ поды в namespace теряют DNS!
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: default-deny-egress
  namespace: production
spec:
  podSelector: {}
  policyTypes:
  - Egress
  egress: []  # Запретить всё, включая DNS!
```

**Симптом:**
```bash
kubectl exec -it <pod> -- nslookup kubernetes.default
# → connection timed out; no servers could be reached
```

**Решение:** Всегда создавайте разрешающую политику для DNS ПЕРЕД Default Deny:

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-dns
  namespace: production
spec:
  podSelector: {}
  policyTypes:
  - Egress
  egress:
  # CoreDNS (ClusterIP)
  - to:
    - namespaceSelector:
        matchLabels:
          kubernetes.io/metadata.name: kube-system
      podSelector:
        matchLabels:
          k8s-app: kube-dns
    ports:
    - protocol: UDP
      port: 53
    - protocol: TCP
      port: 53
```

### Проблема UDP Conntrack Race

При высокой нагрузке UDP-запросы к CoreDNS могут сталкиваться с проблемами conntrack:

```
Pod A → DNS Query (UDP) → conntrack → CoreDNS
Pod B → DNS Query (UDP) → conntrack → CoreDNS
                                        │
                                        ├── Race condition:
                                        │   Ответ Pod A может быть доставлен Pod B
                                        │   Задержка 1-5 секунд или SERVFAIL
```

**Решение:** NodeLocal DNSCache кэширует DNS-ответы локально, минуя conntrack для большинства запросов.

### ndots:5 и лишние DNS-запросы

При `ndots:5` запрос `api.stripe.com` вызывает 4 лишних DNS-запроса:

```
1. api.stripe.com.default.svc.cluster.local → NXDOMAIN
2. api.stripe.com.svc.cluster.local → NXDOMAIN
3. api.stripe.com.cluster.local → NXDOMAIN
4. api.stripe.com → 3.18.0.0/16 (OK)
```

**Решения:**
1. Абсолютные имена с точкой: `api.stripe.com.`
2. Снижение `ndots` до 2 через `dnsConfig`
3. Использование NodeLocal DNSCache

## Практические сценарии

### Сценарий 1: Базовая DNS-политика для production

Минимальный набор правил для DNS:

```yaml
# 1. Default Deny Egress
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: default-deny-egress
  namespace: production
spec:
  podSelector: {}
  policyTypes:
  - Egress
  egress: []
---
# 2. Разрешить DNS (обязательно!)
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-dns
  namespace: production
spec:
  podSelector: {}
  policyTypes:
  - Egress
  egress:
  # CoreDNS (ClusterIP)
  - to:
    - namespaceSelector:
        matchLabels:
          kubernetes.io/metadata.name: kube-system
      podSelector:
        matchLabels:
          k8s-app: kube-dns
    ports:
    - protocol: UDP
      port: 53
    - protocol: TCP
      port: 53
  # NodeLocal DNSCache (если установлен)
  - to:
    - ipBlock:
        cidr: 169.254.20.10/32  # IP NLDC
    ports:
    - protocol: UDP
      port: 53
    - protocol: TCP
      port: 53
```

### Сценарий 2: NodeLocal DNSCache + NetworkPolicy

Установка и настройка NodeLocal DNSCache с NetworkPolicy:

```bash
# Установка через kubectl
kubectl apply -f https://raw.githubusercontent.com/kubernetes/kubernetes/master/cluster/addons/dns/nodelocaldns/nodelocaldns.yaml
```

```yaml
# NetworkPolicy для NodeLocal DNSCache
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-nodelocaldns
  namespace: kube-system
spec:
  podSelector:
    matchLabels:
      k8s-app: node-local-dns
  policyTypes:
  - Ingress
  - Egress
  ingress:
  # От подов (DNS запросы)
  - from:
    - ipBlock:
        cidr: 10.0.0.0/8  # Pod CIDR
    ports:
    - protocol: UDP
      port: 53
    - protocol: TCP
      port: 53
  egress:
  # К CoreDNS
  - to:
    - podSelector:
        matchLabels:
          k8s-app: kube-dns
    ports:
    - protocol: UDP
      port: 53
    - protocol: TCP
      port: 53
  # К upstream DNS (внешние серверы)
  - to:
    - ipBlock:
        cidr: 0.0.0.0/0
    ports:
    - protocol: UDP
      port: 53
    - protocol: TCP
      port: 53
```

### Сценарий 3: DNS-политика с разрешением внутренних сервисов

Ограничение DNS-запросов только до внутренних сервисов:

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-dns-internal-only
  namespace: production
spec:
  podSelector: {}
  policyTypes:
  - Egress
  egress:
  # Только CoreDNS (внутренний)
  - to:
    - namespaceSelector:
        matchLabels:
          kubernetes.io/metadata.name: kube-system
      podSelector:
        matchLabels:
          k8s-app: kube-dns
    ports:
    - protocol: UDP
      port: 53
    - protocol: TCP
      port: 53
  # Нет доступа к внешним DNS!
```

**Симптом:** Под не может разрешить внешние имена (google.com, api.stripe.com).

**Решение:** Добавить правило для внешнего DNS или использовать FQDN-фильтрацию.

### Сценарий 4: Защита от DNS exfiltration

Ограничение DNS-запросов предотвращает туннелирование данных:

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: restrict-dns-exfiltration
  namespace: production
spec:
  podSelector: {}
  policyTypes:
  - Egress
  egress:
  # Только CoreDNS
  - to:
    - namespaceSelector:
        matchLabels:
          kubernetes.io/metadata.name: kube-system
      podSelector:
        matchLabels:
          k8s-app: kube-dns
    ports:
    - protocol: UDP
      port: 53
    - protocol: TCP
      port: 53
  # Заблокировать внешний DNS (другие IP:53)
  # Остальной DNS-трафик будет блокирован Default Deny
```

**Дополнительная защита:** Используйте Cilium для DNS-политик:

```yaml
apiVersion: "cilium.io/v2"
kind: CiliumNetworkPolicy
metadata:
  name: restrict-dns
  namespace: production
spec:
  endpointSelector:
    matchLabels: {}
  egress:
  - toEndpoints:
    - matchLabels:
        "k8s:io.kubernetes.pod.namespace": kube-system
        "k8s:k8s-app": kube-dns
    toPorts:
    - ports:
      - port: "53"
        protocol: ANY
      rules:
        dns:
        # Только разрешенные домены
        - matchPattern: "*.production.svc.cluster.local"
        - matchPattern: "*.default.svc.cluster.local"
        - matchPattern: "api.stripe.com"
```

### Сценарий 5: DNS для приложений с высокой нагрузкой

Оптимизация DNS для приложений с тысячами запросов в секунду:

```yaml
# 1. Снижение ndots
apiVersion: v1
kind: Pod
metadata:
  name: high-qps-app
  namespace: production
spec:
  dnsPolicy: ClusterFirst
  dnsConfig:
    options:
    - name: ndots
      value: "2"  # Вместо 5
    - name: timeout
      value: "2"
    - name: attempts
      value: "2"
  containers:
  - name: app
    image: my-app:latest
---
# 2. NetworkPolicy с разрешением DNS
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-dns-high-qps
  namespace: production
spec:
  podSelector:
    matchLabels:
      app: high-qps-app
  policyTypes:
  - Egress
  egress:
  # DNS
  - to:
    - namespaceSelector:
        matchLabels:
          kubernetes.io/metadata.name: kube-system
      podSelector:
        matchLabels:
          k8s-app: kube-dns
    ports:
    - protocol: UDP
      port: 53
    - protocol: TCP
      port: 53
  # Внешние API (через DNS)
  - to:
    - ipBlock:
        cidr: 0.0.0.0/0
        except:
        - 169.254.169.254/32  # Metadata API
    ports:
    - protocol: TCP
      port: 443
```

### Сценарий 6: Diagnosing DNS-проблемы с NetworkPolicy

Алгоритм диагностики:

```bash
# Шаг 1: Проверка DNS из пода
kubectl exec -it <pod> -n production -- nslookup kubernetes.default
# → Если timeout: проблема с Egress

# Шаг 2: Проверка NetworkPolicy
kubectl get networkpolicy -n production -o yaml | grep -A 10 "port: 53"
# → Если нет правил для port 53: добавить DNS-правило

# Шаг 3: Проверка CoreDNS
kubectl get pods -n kube-system -l k8s-app=kube-dns
kubectl logs -n kube-system -l k8s-app=kube-dns --tail=20

# Шаг 4: Проверка NodeLocal DNSCache
kubectl get pods -n kube-system -l k8s-app=node-local-dns
kubectl logs -n kube-system -l k8s-app=node-local-dns --tail=20

# Шаг 5: Проверка conntrack
conntrack -S | grep dns
# → Если много dropped: проблема с conntrack

# Шаг 6: Тест через debug pod
kubectl run debug --image=nicolaka/netshoot --rm -it -n production -- \
  dig kubernetes.default.svc.cluster.local
```

## Дополнительная информация

### Типичные ошибки

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `SERVFAIL` при DNS-запросе | Conntrack race condition | Установить NodeLocal DNSCache |
| DNS-запросы работают интермитентно | Высокая нагрузка на CoreDNS | Масштабировать CoreDNS, установить NLDC |
| `NXDOMAIN` для внутренних сервисов | DNS-политика блокирует CoreDNS | Разрешить UDP/TCP 53 к CoreDNS |
| Задержки 1-5 сек при DNS | UDP conntrack race | Снизить ndots, установить NLDC |
| Внешние имена не резолвятся | DNS-политика разрешает только CoreDNS | Добавить правило для внешнего DNS |
| DNS-трафик на внешние серверы | Нет ограничений на DNS | Ограничить DNS только CoreDNS |

### NodeLocal DNSCache: Рекомендации

| Параметр | Значение | Описание |
| :--- | :--- | :--- |
| **IP** | `169.254.20.10` | Не конфликтовать с другими сервисами |
| **TTL кеша** | 30 сек | По умолчанию, баланс точности и нагрузки |
| **Upstream** | CoreDNS | Кэш пересылает в CoreDNS при промахе |
| **Conntrack** | Минимизирован | Запросы к NLDC не проходят через conntrack |

### ndots: Оптимизация

| Приложение | Рекомендация | Причина |
| :--- | :--- | :--- |
| **Внутренние сервисы** | `ndots: 5` (по умолчанию) | Быстрое разрешение внутренних имен |
| **Внешние API** | `ndots: 2` или абсолютные имена | Уменьшение лишних DNS-запросов |
| **Микросервисы** | `ndots: 2` + NodeLocal DNSCache | Баланс внутреннего и внешнего DNS |

### См. также

* [DNS в Kubernetes: Глубокое погружение](../../../Networking/dns_deep_dive.md) — архитектура CoreDNS
* [NetworkPolicy: Определения](./definitions.md) — базовые термины
* [NetworkPolicy: Egress паттерны](./egress_patterns.md) — управление исходящим трафиком
* [NetworkPolicy: FQDN-фильтрация](./fqdn_filtering.md) — фильтрация по доменам
