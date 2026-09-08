# NetworkPolicy и Service Mesh: Взаимодействие слоёв безопасности

## Определения

**NetworkPolicy (L3/L4)** — стандартный ресурс Kubernetes для фильтрации трафика на сетевом (IP/порт) и транспортном (TCP/UDP) уровнях OSI. Обеспечивает грубую изоляцию (coarse-grained) между подами и namespace.

**Service Mesh (L7)** — инфраструктурный слой для управления межсервисным трафиком на прикладном уровне (HTTP/gRPC). Обеспечивает mTLS, балансировку, retry, circuit breaking и тонкую авторизацию (fine-grained) по путям и методам.

**AuthorizationPolicy (Istio)** — ресурс Istio для управления доступом на L7-уровне: HTTP-методы (GET/POST), пути (`/api/v1/users`), заголовки, JWT claims. Работает после NetworkPolicy.

**mTLS (Mutual TLS)** — двусторонняя аутентификация через TLS-сертификаты. Service Mesh автоматически управляет сертификатами и шифрует трафик между sidecar-прокси.

**Sidecar Proxy** — контейнер-прокси (Envoy, Linkerd-proxy), автоматически инжектируемый в каждый под Service Mesh. Перехватывает весь сетевой трафик пода для обработки на L7.

**Ambient Mesh** — архитектура Istio без sidecar-контейнеров. Использует `ztunnel` (L4) и `waypoint proxy` (L7) для обработки трафика. Снижает overhead по сравнению со sidecar-моделью.

**Defense in Depth (Эшелонированная защита)** — стратегия безопасности, при которой несколько независимых слоёв защиты последовательно проверяют трафик. NetworkPolicy → Service Mesh → Application.

## Базовые Концепции

### Почему нужен и NetworkPolicy, и Service Mesh

| Критерий | NetworkPolicy (L3/L4) | Service Mesh (L7) |
| :--- | :--- | :--- |
| **Уровень фильтрации** | IP, порт, протокол | HTTP метод, путь, заголовки |
| **Identity** | Pod labels, Namespace | Сертификат (SPIFFE), JWT |
| **Шифрование** | WireGuard (Calico) или нет | mTLS (автоматическое) |
| **Балансировка** | kube-proxy / eBPF | Envoy / Linkerd-proxy |
| **Observability** | Logs, conntrack | Distributed tracing, HTTP metrics |
| **Overhead** | Минимальный | Средний (sidecar или ambient) |
| **Защита от** | Неавторизованный доступ к портам | API abuse, injection, rate limiting |

**Ключевой принцип:** NetworkPolicy — это периметр, Service Mesh — внутренний контроль. NetworkPolicy блокирует трафик до того, как он дойдет до sidecar proxy.

### Порядок проверки трафика

```
Pod A → [NetworkPolicy] → [Sidecar Proxy (Envoy)] → Pod B
            │                       │
            ├── L3/L4 фильтрация    ├── L7 авторизация
            ├── IP/Port rules       ├── HTTP methods
            ├── Namespace bounds    ├── JWT validation
            └── Conntrack           └── Rate limiting
```

**Последовательность:**
1. **NetworkPolicy** проверяет IP/порт. Если заблокировано — трафик не доходит до sidecar.
2. **Sidecar proxy** (Envoy) получает разрешенный NetworkPolicy трафик.
3. **AuthorizationPolicy** (Istio) проверяет HTTP-методы, пути, JWT.
4. Если все проверки пройдены — трафик доставляется целевому поду.

### Типичные проблемы при комбинировании

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Sidecar не может общаться** | NetworkPolicy блокирует порт envoy (15001, 15006) | Разрешить порты sidecar в NetworkPolicy |
| **mTLS не работает** | NetworkPolicy блокирует порт 15001 (inbound) | Добавить `istio` labels в NetworkPolicy |
| **Health checks не проходят** | NetworkPolicy блокирует probe порты | Разрешить порты readiness/liveness probes |
| **Egress к external API** | NetworkPolicy блокирует egress, sidecar не может проксировать | Разрешить egress из sidecar namespace |
| **Performance degradation** | Двойная фильтрация (L3/L4 + L7) | Оптимизировать NetworkPolicy, использовать ambient mesh |

## Практические сценарии

### Сценарий 1: Базовая конфигурация NetworkPolicy + Istio

Когда Service Mesh установлен, NetworkPolicy должен разрешить трафик sidecar proxy:

```yaml
# NetworkPolicy: разрешить трафик между подами с sidecar
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-istio-sidecar
  namespace: production
spec:
  podSelector: {}
  policyTypes:
  - Ingress
  - Egress
  ingress:
  # Разрешить входящий трафик от sidecar proxy (port 15006)
  - from:
    - podSelector:
        matchLabels:
          security.istio.io/tlsMode: istio
    ports:
    - protocol: TCP
      port: 15006
  # Разрешить прямой трафик (health checks)
  - ports:
    - protocol: TCP
      port: 8080
  egress:
  # Разрешить egress через sidecar (port 15001)
  - to:
    - podSelector:
        matchLabels:
          security.istio.io/tlsMode: istio
    ports:
    - protocol: TCP
      port: 15001
  # DNS
  - ports:
    - protocol: UDP
      port: 53
    - protocol: TCP
      port: 53
```

### Сценарий 2: Istio AuthorizationPolicy + NetworkPolicy

Комбинирование L3/L4 и L7 политик:

```yaml
# 1. NetworkPolicy: L3/L4 базовая изоляция
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: backend-isolation
  namespace: production
spec:
  podSelector:
    matchLabels:
      app: backend-api
  policyTypes:
  - Ingress
  ingress:
  - from:
    - podSelector:
        matchLabels:
          app: frontend
    ports:
    - protocol: TCP
      port: 8080
---
# 2. Istio AuthorizationPolicy: L7 тонкая авторизация
apiVersion: security.istio.io/v1
kind: AuthorizationPolicy
metadata:
  name: backend-authz
  namespace: production
spec:
  selector:
    matchLabels:
      app: backend-api
  action: ALLOW
  rules:
  - from:
    - source:
        principals: ["cluster.local/ns/production/sa/frontend-sa"]
    to:
    - operation:
        methods: ["GET", "POST"]
        paths: ["/api/v1/*"]
```

**Эффект:**
- NetworkPolicy разрешает трафик от frontend на порт 8080 (L3/L4)
- Istio проверяет, что principal = frontend-sa и метод GET/POST (L7)
- Если principal другой — Istio блокирует, даже если NetworkPolicy разрешил

### Сценарий 3: Sidecar Injection и NetworkPolicy

При включенном sidecar injection NetworkPolicy должен учитывать порты proxy:

```bash
# Включение sidecar injection для namespace
kubectl label namespace production istio-injection=enabled
```

```yaml
# NetworkPolicy с учетом sidecar портов
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-with-sidecar
  namespace: production
spec:
  podSelector: {}
  policyTypes:
  - Ingress
  - Egress
  ingress:
  # Sidecar inbound (port 15006)
  - ports:
    - protocol: TCP
      port: 15006
  # App port
  - ports:
    - protocol: TCP
      port: 8080
  egress:
  # Sidecar outbound (port 15001)
  - ports:
    - protocol: TCP
      port: 15001
  # DNS
  - ports:
    - protocol: UDP
      port: 53
```

> **Важно:** Если NetworkPolicy блокирует порты 15001/15006, sidecar proxy не сможет обрабатывать трафик, и под станет недоступным.

### Сценарий 4: Ambient Mesh (Istio) + NetworkPolicy

Ambient Mesh использует `ztunnel` (L4) и `waypoint proxy` (L7) вместо sidecar:

```yaml
# NetworkPolicy для Ambient Mesh
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-ambient
  namespace: production
spec:
  podSelector: {}
  policyTypes:
  - Ingress
  - Egress
  ingress:
  # ztunnel (L4 ambient proxy)
  - ports:
    - protocol: TCP
      port: 15001
    - protocol: TCP
      port: 15008
  # App port
  - ports:
    - protocol: TCP
      port: 8080
  egress:
  # ztunnel outbound
  - ports:
    - protocol: TCP
      port: 15001
    - protocol: TCP
      port: 15008
  # DNS
  - ports:
    - protocol: UDP
      port: 53
```

### Сценарий 5: Calico + Istio Integration

Комбинирование Calico GlobalNetworkPolicy и Istio AuthorizationPolicy:

```yaml
# 1. Calico: Глобальный Default Deny (Tier 1)
apiVersion: projectcalico.org/v3
kind: GlobalNetworkPolicy
metadata:
  name: global-default-deny
spec:
  order: 2000
  selector: "all()"
  types: [Ingress, Egress]
  ingress:
  - action: Deny
  egress:
  - action: Deny
---
# 2. Calico: Разрешить DNS (Tier 1)
apiVersion: projectcalico.org/v3
kind: GlobalNetworkPolicy
metadata:
  name: allow-dns-global
spec:
  order: 50
  selector: "all()"
  types: [Egress]
  egress:
  - action: Allow
    protocol: UDP
    destination:
      selector: "k8s-app == 'kube-dns'"
      namespaceSelector: "kubernetes.io/metadata.name == 'kube-system'"
      ports: [53]
---
# 3. Calico: Разрешить Istio control plane (Tier 1)
apiVersion: projectcalico.org/v3
kind: GlobalNetworkPolicy
metadata:
  name: allow-istio-control-plane
spec:
  order: 60
  selector: "all()"
  types: [Egress]
  egress:
  - action: Allow
    destination:
      namespaceSelector: "kubernetes.io/metadata.name == 'istio-system'"
    ports: [15012, 15017]
---
# 4. Istio: L7 авторизация (вне Calico tiers)
apiVersion: security.istio.io/v1
kind: AuthorizationPolicy
metadata:
  name: backend-authz
spec:
  selector:
    matchLabels:
      app: backend
  action: ALLOW
  rules:
  - from:
    - source:
        principals: ["cluster.local/ns/production/sa/frontend"]
```

### Сценарий 6: Мониторинг обоих слоёв

```yaml
# Prometheus ServiceMonitor для Istio
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: istio-mesh-metrics
  namespace: monitoring
spec:
  selector:
    matchLabels:
      istio: prometheus
  endpoints:
  - port: http-prometheus
    interval: 30s
---
# Grafana Dashboard: Istio Mesh Dashboard (ID: 7639)
# Ключевые метрики:
# - istio_requests_total (L7 HTTP metrics)
# - istio_request_duration_milliseconds
# - istio_tcp_connections_opened_total
# - envoy_upstream_cx_active (активные соединения)
```

## Дополнительная информация

### Рекомендации по использованию

| Сценарий | Рекомендация |
| :--- | :--- |
| **Простая изоляция (2-3 сервиса)** | Только NetworkPolicy |
| **Микросервисы с HTTP API** | NetworkPolicy + Istio AuthorizationPolicy |
| **mTLS обязателен** | Service Mesh (обязательно) + NetworkPolicy |
| **Высокая нагрузка (>10K RPS)** | Ambient Mesh + NetworkPolicy (minimize L7 overhead) |
| **PCI DSS / HIPAA** | NetworkPolicy + Service Mesh + ANP |

### Performance Impact

| Компонент | Overhead на request | Latency Impact |
| :--- | :--- | :--- |
| **NetworkPolicy (iptables)** | ~1-5 μs | Минимальный |
| **NetworkPolicy (eBPF)** | ~0.1-1 μs | Минимальный |
| **Istio sidecar (Envoy)** | ~0.5-2 ms | Средний |
| **Istio ambient (ztunnel)** | ~0.1-0.5 ms | Низкий |
| **mTLS handshake** | ~1-5 ms (первый), ~0 (keep-alive) | Первый запрос |

> **Кросс-ссылка:** Производительность NetworkPolicy — [Performance](./performance.md)

### Связанные темы

* [Service Mesh: Концепции](../../Service_Mesh/service_mesh_concepts.md) — общие концепции
* [Istio: Архитектура](../../Service_Mesh/istio_architecture.md) — детали Istio
* [Istio: Security Policies](../../Service_Mesh/istio-security-policies.md) — AuthorizationPolicy
* [NetworkPolicy: Определения](./definitions.md) — базовые определения
* [eBPF в Kubernetes](../../Networking/Network/CNI/ebpf.md) — eBPF dataplane
* [Calico + Istio](../../Security/network_policies/Calico/scenarios.md) — Calico сценарии
