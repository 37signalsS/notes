# NetworkPolicy и Ingress Controller: Взаимодействие

## Определения

**Ingress Controller** — компонент Kubernetes, реализующий ресурс Ingress (или Gateway API) для маршрутизации внешнего HTTP/HTTPS-трафика на поды внутри кластера. Представляет собой reverse-proxy (NGINX, Traefik, HAProxy, Envoy), который разворачивается как Deployment или DaemonSet и обрабатывает входящий North-South трафик.

**Ingress-to-Pod path** — путь трафика от внешнего клиента через Ingress Controller до целевого пода: Client → External LB/NodePort → Ingress Controller Pod → Service (ClusterIP) → Target Pod. На каждом из этих этапов NetworkPolicy может фильтровать трафик.

**externalTrafficPolicy: Local** — параметр Service, предотвращающий SNAT (Source NAT) при маршрутизации внешнего трафика. Сохраняет реальный IP клиента, но требует, чтобы Ingress Controller имел доступ ко всем целевым подам через маршрутизацию (без прыжков через другие узлы).

**IngressClass** — ресурс Kubernetes, определяющий какой Ingress Controller должен обрабатывать конкретный ресурс Ingress. В кластере может быть несколько контроллеров (internal/external), каждый с собственными NetworkPolicy.

## Базовые Концепции

### Проблема: Ingress Controller и NetworkPolicy

При применении Default Deny Ingress к namespace, где работает Ingress Controller, внешний трафик блокируется. Ingress Controller становится unable to проксировать запросы к подам приложений, так как его трафик проходит через Service и попадает под действие NetworkPolicy целевого namespace.

### Порядок проверки трафика

```
Внешний клиент
    │
    ▼
[NodePort / External LB]
    │
    ▼
[Ingress Controller Pod]  ← NetworkPolicy Ingress namespace
    │
    ▼
[Service ClusterIP]       ← kube-proxy / IPVS
    │
    ▼
[Target Pod]              ← NetworkPolicy Target namespace
```

NetworkPolicy проверяется дважды:
1. В namespace Ingress Controller (входящий трафик от клиентов)
2. В namespace целевого приложения (трафик от Ingress Controller)

### Типичные порты Ingress Controller

| Контроллер | Inbound порты | Протокол | Примечание |
| :--- | :--- | :--- | :--- |
| **NGINX** | 80, 443 | TCP | Основные entrypoint'ы |
| **Traefik** | 80, 443, 8080 | TCP | 8080 для dashboard |
| **HAProxy** | 80, 443, 1936 | TCP | 1936 для stats |
| **Envoy Gateway** | 80, 443 | TCP | Стандартные порты |

### Влияние hostNetwork

Если Ingress Controller работает с `hostNetwork: true` (распространено в bare-metal), его трафик НЕ фильтруется NetworkPolicy, так как под использует сетевой стек хоста. NetworkPolicy будет фильтровать только трафик на стороне целевого пода.

## Практические сценарии

### Сценарий 1: NGINX Ingress Controller + Default Deny

Полная изоляция namespace с web-приложениями при сохранении доступа через NGINX Ingress:

```yaml
# 1. Default Deny для namespace приложений
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: default-deny-all
  namespace: production
spec:
  podSelector: {}
  policyTypes:
  - Ingress
  - Egress
---
# 2. Разрешить Ingress от NGINX Controller
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-ingress-nginx
  namespace: production
spec:
  podSelector: {}
  policyTypes:
  - Ingress
  ingress:
  - from:
    # Из namespace ingress-nginx
    - namespaceSelector:
        matchLabels:
          kubernetes.io/metadata.name: ingress-nginx
      podSelector:
        matchLabels:
          app.kubernetes.io/name: ingress-nginx
    ports:
    - protocol: TCP
      port: 8080
    - protocol: TCP
      port: 8443
---
# 3. Разрешить DNS для приложений
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

### Сценарий 2: Мульти-tenant с изоляцией Ingress

Разные Ingress Controller для разных тенантов с полной сетевой изоляцией:

```yaml
# Tenant A: internal-ingress
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-internal-ingress
  namespace: tenant-a
spec:
  podSelector: {}
  policyTypes:
  - Ingress
  ingress:
  - from:
    - namespaceSelector:
        matchLabels:
          kubernetes.io/metadata.name: ingress-internal
    ports:
    - protocol: TCP
      port: 8080
---
# Tenant B: external-ingress (другой контроллер)
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-external-ingress
  namespace: tenant-b
spec:
  podSelector: {}
  policyTypes:
  - Ingress
  ingress:
  - from:
    - namespaceSelector:
        matchLabels:
          kubernetes.io/metadata.name: ingress-external
    ports:
    - protocol: TCP
      port: 8080
```

### Сценарий 3: Ingress Controller в namespace с Default Deny

NetworkPolicy для самого Ingress Controller, если он работает в namespace с изоляцией:

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-nginx-egress
  namespace: ingress-nginx
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: ingress-nginx
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
  # Доступ к подам приложений во всех namespace
  - to:
    - namespaceSelector: {}
    ports:
    - protocol: TCP
      port: 8080
    - protocol: TCP
      port: 8443
```

### Сценарий 4: Traefik + Middleware + NetworkPolicy

Особенности работы Traefik с NetworkPolicy:

```yaml
# Traefik работает в namespace traefik
# Middleware (rate-limit, auth) обрабатывается ДО проксирования на под
# NetworkPolicy фильтрует трафик между Traefik и целевым подом

apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-traefik-to-app
  namespace: production
spec:
  podSelector:
    matchLabels:
      app: my-app
  policyTypes:
  - Ingress
  ingress:
  - from:
    - namespaceSelector:
        matchLabels:
          kubernetes.io/metadata.name: traefik
      podSelector:
        matchLabels:
          app.kubernetes.io/name: traefik
    ports:
    - protocol: TCP
      port: 8080
```

### Сценарий 5: HAProxy с socks-сокетом и NetworkPolicy

HAProxy.stats и health-check требуют дополнительных правил:

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-haproxy-healthcheck
  namespace: production
spec:
  podSelector:
    matchLabels:
      app: web-app
  policyTypes:
  - Ingress
  ingress:
  - from:
    - namespaceSelector:
        matchLabels:
          kubernetes.io/metadata.name: ingress-haproxy
    ports:
    - protocol: TCP
      port: 80
    - protocol: TCP
      port: 443
```

### Сценарий 6: ExternalTrafficPolicy: Local + NetworkPolicy

Сохранение Source IP при использовании Ingress:

```yaml
apiVersion: v1
kind: Service
metadata:
  name: my-app
  namespace: production
spec:
  type: LoadBalancer
  externalTrafficPolicy: Local  # Сохраняет Source IP
  selector:
    app: my-app
  ports:
  - port: 80
    targetPort: 8080
---
# NetworkPolicy должен учитывать, что трафик приходит
# с IP узла, а не с IP Ingress Controller
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-external-with-source-ip
  namespace: production
spec:
  podSelector:
    matchLabels:
      app: my-app
  policyTypes:
  - Ingress
  ingress:
  - from:
    # Все поды в namespace ingress-nginx
    - namespaceSelector:
        matchLabels:
          kubernetes.io/metadata.name: ingress-nginx
    ports:
    - protocol: TCP
      port: 8080
```

## Дополнительная информация

### Типичные ошибки

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| 503 от Ingress | NetworkPolicy блокирует трафик от Controller к поду | Добавить Ingress-правило для namespace Controller |
| Ingress работает, но部分请求 падают | Egress DNS блокируется в namespace Controller | Разрешить DNS в namespace Controller |
| Connection refused от Ingress | Target pod не слушает порт, указанный в NetworkPolicy | Сверить порты в NetworkPolicy и поде |
| Source IP не сохраняется | `externalTrafficPolicy: Cluster` вместо `Local` | Установить `externalTrafficPolicy: Local` |

### Чек-лист настройки NetworkPolicy для Ingress

| # | Действие | Приоритет |
| :--- | :--- | :--- |
| 1 | Определить namespace Ingress Controller | Критический |
| 2 | Разрешить Egress из namespace Controller (DNS + все поды приложений) | Критический |
| 3 | Разрешить Ingress к подам приложений от Controller | Критический |
| 4 | Проверить порты entrypoint'ов Controller (80, 443, 8080) | Высокий |
| 5 | Учесть hostNetwork (если используется) | Высокий |
| 6 | Проверить работу с `externalTrafficPolicy: Local` | Средний |

### См. также

* [NetworkPolicy: Лучшие практики](./best_practices.md) — рекомендации по проектированию
* [NetworkPolicy: Реализация CNI-плагинами](./cni_implementation.md) — сравнение CNI
* [Ingress: Обзор](../../Ingress/overview.md) — архитектура Ingress Controller
* [Traffic Path](../traffic_path.md) — полный путь пакета в Kubernetes

### Gateway API и NetworkPolicy

Gateway API — современная замена Ingress, требующая аналогичной настройки NetworkPolicy:

```yaml
# Gateway API: Gateway Controller
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: production-gateway
  namespace: infra
spec:
  gatewayClassName: istio
  listeners:
  - name: http
    port: 80
    protocol: HTTP
  - name: https
    port: 443
    protocol: HTTPS
---
# NetworkPolicy для Gateway Controller
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-gateway-controller
  namespace: infra
spec:
  podSelector:
    matchLabels:
      istio: ingressgateway
  policyTypes:
  - Ingress
  - Egress
  ingress:
  # Внешний трафик
  - from:
    - ipBlock:
        cidr: 0.0.0.0/0
    ports:
    - protocol: TCP
      port: 80
    - protocol: TCP
      port: 443
  egress:
  # DNS
  - to:
    - namespaceSelector: {}
      podSelector:
        matchLabels:
          k8s-app: kube-dns
    ports:
    - protocol: UDP
      port: 53
  # К целевым подам приложений
  - to:
    - namespaceSelector:
        matchLabels:
          kubernetes.io/metadata.name: production
    ports:
    - protocol: TCP
      port: 8080
    - protocol: TCP
      port: 8443
---
# NetworkPolicy для целевых подов
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-from-gateway
  namespace: production
spec:
  podSelector: {}
  policyTypes:
  - Ingress
  ingress:
  # От Gateway Controller
  - from:
    - namespaceSelector:
        matchLabels:
          kubernetes.io/metadata.name: infra
      podSelector:
        matchLabels:
          istio: ingressgateway
    ports:
    - protocol: TCP
      port: 8080
```

**Отличия Gateway API от Ingress:**
| Критерий | Ingress | Gateway API |
| :--- | :--- | :--- |
| Namespace controller | Обычно `ingress-nginx` | Может быть `infra`, `gateway-system` |
| Порты | 80, 443 | 80, 443 + кастомные |
| Multi-protocol | Ограничен | HTTP, HTTPS, TCP, UDP, gRPC |
| NetworkPolicy | Ingress Controller namespace | Gateway Controller namespace |
