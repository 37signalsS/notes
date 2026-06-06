# L4-маршрутизация — TCPRoute и UDPRoute

## Определения

**TCPRoute** — ресурс Gateway API, предназначенный для маршрутизации TCP-трафика (базы данных, SSH, кастомные протоколы). На текущий момент (2026 год) находится в статусе `v1alpha2` (Alpha).

**UDPRoute** — ресурс Gateway API для маршрутизации UDP-трафика (DNS, игровые серверы, VoIP). Находится в статусе `v1alpha2` (Alpha).

**L4-маршрутизация** — передача трафика на транспортном уровне (TCP/UDP) без анализа содержимого пакетов прикладного уровня. В отличие от L7-маршрутизации (HTTP/gRPC), контроллер не расшифровывает протокол и оперирует только портами и IP-адресами.

## Базовые концепции

### Область применения
Gateway API стандартизирует управление трафиком, который не относится к HTTP. Основные сценарии использования:
- Базы данных: PostgreSQL, MySQL, Redis.
- Системные службы: SSH, протоколы управления.
- Сетевые службы: DNS, NTP.
- Специализированный трафик: игровые серверы, VoIP (SIP), потоковое мультимедиа.

### Статус ресурсов
| Ресурс | Версия API | Статус |
| :--- | :--- | :--- |
| **TCPRoute** | `gateway.networking.k8s.io/v1alpha2` | Alpha |
| **UDPRoute** | `gateway.networking.k8s.io/v1alpha2` | Alpha |
| **Gateway** | `gateway.networking.k8s.io/v1` | GA |

**Важно:** Ресурсы в статусе Alpha могут подвергаться изменениям, нарушающим обратную совместимость. В продуктивных средах их следует использовать с осторожностью.

### Разделение ответственности
В отличие от `HTTPRoute`, настройка L4-маршрутов требует более тесной координации с администратором кластера:
1. **Администратор кластера:** должен сконфигурировать контроллер (шлюз) на прослушивание специфических TCP/UDP-портов в инфраструктуре.
2. **Разработчик приложения:** создает ресурсы `Gateway` (listener) и `TCPRoute`/`UDPRoute` для направления входящего трафика на сервис.

### Ограничения и альтернативы
**Недостатки L4 через L7-прокси:**
- Большинство прокси-серверов (Traefik, Envoy, Nginx) вносят дополнительные накладные расходы при пробросе TCP-соединений.
- Требуется явное открытие портов на уровне балансировщика.

**Альтернативные подходы:**
- `NodePort` — прямой доступ к сервису через порт на узле.
- `LoadBalancer` — использование внешнего балансировщика облачного провайдера.
- **[MetalLB](../metallb.md)** — реализация LoadBalancer для bare-metal инфраструктуры.

## Практические сценарии

### Настройка TCPRoute (на примере SSH через Traefik)

**1. Подготовка контроллера (Администратор)**
Необходимо открыть порт в конфигурации Helm Chart (например, `values.yaml` для Traefik):
```yaml
ports:
  ssh:
    port: 3000
    expose: true
    protocol: TCP
experimental:
  kubernetesGateway:
    enabled: true
```

**2. Создание шлюза (Gateway)**
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

**3. Настройка маршрута (TCPRoute)**
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

### Настройка UDPRoute (на примере DNS)
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

**Связанные темы:**
- [Определения Gateway API](./definitions.md) — базовые концепции и архитектура.
- [Расширенные функции маршрутизации](./routing_features.md) — фильтры и L7-возможности.
- [Базовые сценарии](./practical_basic.md) — примеры настройки HTTPRoute.
- [Реализации: Traefik](./traefik.md) — особенности работы с контроллером Traefik.

**Официальная документация:**
- [Спецификация TCPRoute](https://gateway-api.sigs.k8s.io/api-types/tcproute/)
- [Спецификация UDPRoute](https://gateway-api.sigs.k8s.io/api-types/udproute/)

**Родительская тема:** [Gateway API](./definitions.md)
