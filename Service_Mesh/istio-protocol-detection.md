# Определение протокола трафика (Protocol Detection) в Istio

## Определения

**Port Naming Conventions (соглашения об именах портов)** — в Istio протокол трафика сервиса определяется по имени порта в Kubernetes `Service.ports[].name` через префиксы: `http-`, `http2-`, `grpc-`, `tcp-`, `tls-`, `https-` и известным именам (`mysql`, `redis`, `mongo`, `kafka` и др.).

**Protocol Sniffing** — автоматическое определение протокола Envoy по первым байтам соединения (для портов без явного имени): если данные похожи на HTTP-запрос — трафик обрабатывается как HTTP (L7), иначе — как TCP (L4).

**ALPN (Application-Layer Protocol Negotiation)** — механизм TLS, в котором клиент и сервер согласуют протокол внутри ClientHello (`http/1.1`, `h2`, `http/3`) ещё до начала прикладного обмена.

**h2c (HTTP/2 over cleartext TCP)** — HTTP/2 без TLS. Клиент анонсирует HTTP/2 через «Prior Knowledge» (магический префикс `PRI * HTTP/2.0`) или апгрейд. Используется для gRPC внутри кластера (mesh без внешнего TLS).

**`appProtocol`** — поле Kubernetes `Service.ports[].appProtocol`, позволяющее явно указать протокол (например, `kubernetes.io/h2c`) без следования соглашениям об именах.

**Protocol Detection Timeout** — таймаут, в течение которого Envoy «слушает» первые байты соединения, чтобы решить, это HTTP/2 prior-knowledge или HTTP/1.x (по умолчанию 5 секунд). Влияет на задержку первого байта для неявных протоколов.

---

## Основные концепции

### Как Istio решает, что это за протокол

Определение протокола происходит на двух уровнях:

1. **Статически (по реестру)** — по `ports[].name` сервиса при построении listener'ов:
   - `http-*`, `grpc-*`, `http2-*`, `https-*` → HTTP/HTTPS (L7);
   - `tcp-*` → TCP (L4);
   - известные имена (`mysql`, `redis`, `mongo`, `kafka`) → соответствующие протоколы;
   - `tls-*` → TLS (с опциональным SNI).
2. **Динамически (sniffing)** — если имя порта не распознано (или порт без имени), Envoy определяет протокол по содержимому:
   - для TCP-трафика без TLS-префикса — проверяет, похожи ли первые байты на HTTP-метод (`GET`, `POST`, …) → HTTP, иначе TCP;
   - для TLS-трафика — по ALPN/SNI из ClientHello;
   - для HTTP/2 prior-knowledge — по магическому префиксу `PRI * HTTP/2.0`.

### Почему это важно на практике

- **Маршрутизация**: HTTP-трафик маршрутизируется по `HTTPRoute`/`VirtualService` (хосты, пути, заголовки); TCP — только по порту/SNI.
- **Политики L7**: `AuthorizationPolicy` с `method`/`path`, rate limiting на пути, зеркалирование и т.п. работают только если протокол распознан как HTTP.
- **Телеметрия**: метрики (`requests_total`, `response_duration_seconds`) собираются только для HTTP.
- **Задержка**: при sniffing Envoy ждёт таймаут определения протокола (до 5 секунд при неудаче), прежде чем отнести соединение к TCP; явное объявление протокола убирает эту задержку.

### Значения протоколов для портов

| Имя порта | Протокол | Поведение Envoy |
| :--- | :--- | :--- |
| `http` / `http-*` | HTTP/1.x | L7 маршрутизация по Host/path |
| `grpc` / `grpc-*` | HTTP/2 (gRPC) | L7, HTTP/2 |
| `http2` / `http2-*` | HTTP/2 (h2c) | L7, HTTP/2 prior knowledge |
| `https` / `https-*` | HTTPS | TLS terminate или SNI |
| `tls` / `tls-*` | TLS | L4 с маршрутизацией по SNI |
| `tcp` / `tcp-*` | TCP | L4 |
| `mysql`, `redis`, `mongo`, `kafka` | специфичные | L4 с известным фильтром/анализатором |

### h2c и gRPC: почему без явного протокола они ломаются

gRPC требует HTTP/2. Envoy умеет детектить h2c (prior knowledge), но это происходит в рамках таймаута определения протокола. На практике gRPC через неименнованный порт часто:
- обрабатывается как HTTP/1.x → 505 HTTP Version Not Supported;
- либо ловится через HTTP/2 upgrade с задержкой.

**Решение**: явно указывать `appProtocol: kubernetes.io/h2c` (или имя порта `grpc-*`/`http2-*`).

### Keepalive (TCP-level)

- **Upstream (исходящие)** — настраивается в `DestinationRule.trafficPolicy.connectionPool.tcp.keepalive`: Envoy поддерживает жизнеспособность idle-соединений до бэкенда (полезно при долгих простоях под NAT/балансировщиками).
- **Inbound (входящие)** — глобально через `ProxyConfig.tcpKeepalive` (`meshConfig.defaultConfig.tcpKeepalive`).
- Примечание: в Istio API поля называется `proveTime`, `proveInterval`, `proves` (известный исторический перекос в неймингах от `probe`); в k8s/enovy это `keepalive_time`/`keepalive_interval`/`keepalive_probes`.

---

## Практические сценарии

### Сценарий 1: Явное именование портов сервиса

```yaml
apiVersion: v1
kind: Service
metadata:
  name: my-service
spec:
  selector:
    app: my-service
  ports:
  - name: http-metrics
    port: 8080
    targetPort: 8080
  - name: grpc-api
    port: 9090
    targetPort: 9090
  - name: tcp-cache
    port: 6379
    targetPort: 6379
```

Проверка определенного протокола:

```bash
kubectl get service my-service -o jsonpath='{.spec.ports[*].name}'
# → http-metrics grpc-api tcp-cache

# Envoy строит HTTP-кластер для 8080 (L7), HTTP/2 для 9090, TCP для 6379
istioctl proxy-config cluster deploy/anything -n production | grep my-service
# → outbound|8080||my-service.production.svc.cluster.local ...
```

### Сценарий 2: `appProtocol` для нестандартных имён (h2c/gRPC)

Когда имя порта задаёт приложение и переименовать нельзя:

```yaml
apiVersion: v1
kind: Service
metadata:
  name: grpc-app
spec:
  selector:
    app: grpc-app
  ports:
  - name: custom-name
    port: 50051
    targetPort: 50051
    appProtocol: kubernetes.io/h2c
```

```bash
# Проверка что трафик обрабатывается как HTTP/2 (cluster type EDS, HTTP route)
istioctl proxy-config listener deploy/client -n production --port 50051 -o json | jq -r '.filters[].typed_config'
# → visible: http_connection_manager ... http2_protocol_options
```

### Сценарий 3: Диагностика неверно определённого протокола

```bash
# 1. Что прокси думает про соседний сервис
istioctl proxy-config listener deploy/my-app -n production --port 8080 -o json | jq '.name'

# 2. Если HTTP-методы не видны → вероятно TCP-маршрут
istioctl proxy-config route deploy/my-app -n production --name 8080
# → (пусто) — значит интерпретируется как TCP

# 3. Проверка через реальный запрос (gRPC health)
kubectl exec deploy/client -n production -- grpcurl -plaintext grpc-app:50051 opentelemetry.proto.collector.trace.v1.TraceService/Export
# → (пустой вывод/ошибка при HTTP/1.1) vs 200 при корректном h2c
```

### Сценарий 4: Keepalive для длинных idle-соединений

```yaml
apiVersion: networking.istio.io/v1
kind: DestinationRule
metadata:
  name: db-keepalive
spec:
  host: db-service
  trafficPolicy:
    connectionPool:
      tcp:
        keepalive:
          proveTime: 30       # первая проба через 30с idle
          proveInterval: 10   # интервал проб
          proves: 3           # число неудачных проб до разрыва
```

```bash
# Проверка применения (в config dump кластера)
istioctl proxy-config cluster deploy/my-app -n production -o json | grep -A6 tcp
# → "upstream_connection_options": {"tcp_keepalive": {...}}
```

### Сценарий 5: Протоколы на listener'ах шлюза (Gateway API)

`applicationProtocol` в `Gateway` указывает допустимые протоколы для сервера:

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: external-gateway
  namespace: istio-ingress
spec:
  gatewayClassName: istio
  listeners:
  - name: http2
    protocol: HTTP
    port: 80
    applicationProtocol: h2c
  - name: https
    protocol: HTTPS
    port: 443
    applicationProtocol:
    - http/1.1
    - http/2
```

Проверка принятых ALPN-протоколов:

```bash
istioctl proxy-config listener deploy/istio-ingressgateway -n istio-ingress
# → 0.0.0.0:8080  ... application_protocols: h2c
# → 0.0.0.0:8443  ... application_protocols: http/1.1 http/2
```

---

## Типичные ошибки и устранение неполадок

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `505 HTTP Version Not Supported` для gRPC | HTTP/2 не распознан (порт без `grpc-`/`h2c`) | `appProtocol: kubernetes.io/h2c`, имя порта `grpc-*` |
| HTTP-маршруты не срабатывают (404/логику нет) | Протокол определён как TCP (нет имени/не распознан) | Явное имя `http-*` / `appProtocol: http` |
| Первая задержка ответа > 1–2 сек | Protocol detection timeout при sniffing | Задать протокол явно, исключить sniffing |
| gRPC-стриминг рвётся на idle-соединениях | Нет keepalive, соединение убито NAT | Настроить `connectionPool.tcp.keepalive` или ping gRPC |
| TCP-трафик маршрутизируется как HTTP | Sniffing «угадал» HTTP (данные похожи) | Перевести порт в `tcp-*`, проверить `istioctl proxy-config route` |
| TLS не терминируется (передаётся как TCP) | Порт без `https-`/`tls-`, нет ALPN | Присвоить имя `https-*` или включить SNI в listener'ах шлюза |
| `Access log: protocol: unknown` | Нет информации о протоколе в access-логах | В `Telemetry API` указать `response_flags`/`protocol`; протокол сервиса задать явно |

---

## Лучшие практики эксплуатации

1. **Всегда именуйте порты** по соглашениям (`http-`, `grpc-`, `tls-`, `tcp-`, `mysql-*` и т.д.) — это избавляет от sniffing и его задержек.
2. **gRPC — явно**: `grpc-*` или `appProtocol: kubernetes.io/h2c`, никогда не полагайтесь на автоматическое определение HTTP/2.
3. **`appProtocol` для унификации**: используйте его как единый источник протокола вместо неоднозначных имён.
4. **Проверяйте `istioctl proxy-config listener/route`** после добавления нового сервиса — быстрая детекция «TCP-вместо-HTTP».
5. **Keepalive для долгих потоков** (gRPC, WebSocket, базы через NAT/LB) — настраивайте `tcp.keepalive` в `DestinationRule`.
6. **Шлюз**: явно перечисляйте `applicationProtocol` (http/1.1, http/2) на HTTPS-listeners, чтобы не терять HTTP/2-совместимость клиентов.

---

## Дополнительная информация

### Связь с другими темами

- Определение протокола напрямую влияет на маршрутизацию и политики: [Управление трафиком в Service Mesh](./traffic_management.md).
- `appProtocol` и listener'ы шлюза — [Входящий шлюз (Ingress Gateway)](./istio-ingress-gateway.md).
- Keepalive и connection pool также относятся к производительности: [Тюнинг производительности Istio](./istio-performance-tuning.md).
- HTTP/2 между сервисами mesh (для gRPC) перешивается через mTLS независимо от `h2c`.

### См. также

- [Прокси Sidecar: реализации и сценарии](./proxy_sidecar.md)
- [Service Mesh: основные концепции](./service_mesh_concepts.md)
- [Работа с gRPC в networking](../Networking/ServicesAndTools/grpc_overview.md)

Документация: [Istio: Protocol Selection](https://istio.io/latest/docs/ops/configuration/traffic-management/protocol-selection/).