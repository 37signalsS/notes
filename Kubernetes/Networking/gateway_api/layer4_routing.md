# Gateway API L4 Routing — TCPRoute и UDPRoute

## Определения

**TCPRoute** — ресурс Gateway API для маршрутизации TCP-трафика (базы данных, SSH, кастомные протоколы). Статус: `v1alpha2` (Alpha).

**UDPRoute** — ресурс Gateway API для маршрутизации UDP-трафика (DNS, игровые серверы, VoIP). Статус: `v1alpha2` (Alpha).

**L4 маршрутизация** — маршрутизация на транспортном уровне (TCP/UDP) без анализа содержимого пакетов. В отличие от L7 (HTTP/gRPC), не требует понимания прикладного протокола.

## Базовые концепции

### Область применения

Gateway API стандартизирует маршрутизацию L4 для трафика, не относящегося к HTTP: базы данных (PostgreSQL, MySQL), SSH, DNS, игровые серверы, VoIP.

### Статус ресурсов (2026)

| Ресурс | API Version | Статус |
| :--- | :--- | :--- |
| **TCPRoute** | `gateway.networking.k8s.io/v1alpha2` | Alpha |
| **UDPRoute** | `gateway.networking.k8s.io/v1alpha2` | Alpha |
| **Gateway** | `gateway.networking.k8s.io/v1` | GA |

**Рекомендация:** Ресурсы в статусе Alpha могут измениться в будущих версиях. Использовать с осторожностью в production.

### Разделение ответственности

В отличие от `HTTPRoute`, настройка `TCPRoute`/`UDPRoute` требует координации с администратором кластера:

1. **Администратор** настраивает контроллер на прослушивание TCP/UDP-портов.
2. **Разработчик** создаёт Gateway listener и Route для направления трафика.

### Ограничения и альтернативы

**Недостатки L4 через L7-прокси:**
- Прокси 7-го уровня (Traefik, NGINX, Envoy) не предназначены для сквозного проброса TCP-соединений.
- Возможны дополнительные задержки по сравнению с прямым доступом.
- Требуется участие администратора для настройки портов.

**Альтернативы для простых случаев:**
- `NodePort` — прямой доступ к сервису через порт на каждой ноде.
- `LoadBalancer` — внешний балансировщик для сервиса.
- `MetalLB` — программная реализация LoadBalancer для bare-metal.

## Практические сценарии

### Настройка TCPRoute (SSH через Traefik)

**Шаг 1: Настройка контроллера (администратор)**

```yaml
# values.yaml для Traefik Helm Chart
ports:
  ssh:
    port: 3000
    expose: true
    protocol: TCP
experimental:
  kubernetesGateway:
    enabled: true
```

**Шаг 2: Создание Gateway**

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: traffic-gateway-ssh
spec:
  gatewayClassName: traefik
  listeners:
  - name: ssh
    protocol: TCP
    port: 3000
    allowedRoutes:
      kinds:
      - kind: TCPRoute
```

**Шаг 3: Создание TCPRoute**

```yaml
apiVersion: gateway.networking.k8s.io/v1alpha2
kind: TCPRoute
metadata:
  name: ssh-route
spec:
  parentRefs:
  - name: traffic-gateway-ssh
    sectionName: ssh
  rules:
  - backendRefs:
    - name: ubuntu-ssh-service
      port: 22
```

### Настройка TCPRoute (PostgreSQL)

```yaml
apiVersion: gateway.networking.k8s.io/v1alpha2
kind: TCPRoute
metadata:
  name: postgres-route
  namespace: default
spec:
  parentRefs:
  - name: tcp-gateway
    sectionName: postgres
  rules:
  - backendRefs:
    - name: postgres-service
      port: 5432
```

### Настройка UDPRoute (DNS)

```yaml
apiVersion: gateway.networking.k8s.io/v1alpha2
kind: UDPRoute
metadata:
  name: dns-route
  namespace: default
spec:
  parentRefs:
  - name: udp-gateway
    sectionName: dns
  rules:
  - backendRefs:
    - name: coredns-service
      port: 53
```

## Дополнительная информация

L7-маршрутизация (HTTP/gRPC): [Расширенные функции маршрутизации](./routing_features.md).

Базовые примеры HTTPRoute: [Базовые сценарии](./practical_basic.md).

Концепции Gateway API: [Определения](./definitions.md).

Реализации: [Envoy Gateway](./envoy_gateway.md), [Traefik](./traefik.md).

Официальная документация: [Gateway API TCPRoute](https://gateway-api.sigs.k8s.io/api-types/tcproute/), [UDPRoute](https://gateway-api.sigs.k8s.io/api-types/udproute/).
