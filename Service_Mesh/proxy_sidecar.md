# Proxy Sidecar: Envoy, Linkerd Proxy

Прокси в модели sidecar — это прозрачный сетевой посредник, запускаемый рядом с приложением в одном Pod, через который проходит исходящий и входящий трафик. Перехват осуществляется на уровне сетевой плоскости узла (например, с помощью iptables), а логика маршрутизации, балансировки, шифрования и наблюдаемости реализуется в самом прокси. В современных service mesh основными реализациями служат Envoy (обычно в составе Istio) и Linkerd Proxy (linkerd2-proxy).

## Архитектура и протоколы

### Envoy

-   Высокопроизводительный L4/L7-прокси на C++ с модульной “filter chain”.
-   Поддержка HTTP/1.1, HTTP/2, HTTP/3, gRPC, TCP/UDP, TLS/mTLS.
-   Динамическая конфигурация через семейство xDS (кластеры, маршруты, листенеры).
-   Расширяемость: HTTP-фильтры, Lua/WASM-плагины, продвинутые политики ретраев и circuit breaking.

### Linkerd Proxy

-   Компактный прокси на Rust с акцентом на безопасность и малый overhead.
-   Поддержка HTTP/1.x, HTTP/2, gRPC; TCP-проброс; автоматический mTLS.
-   Простая модель: большинство настроек выносится в контроллер; прокси получает конфигурацию автоматически.
-   Без плагинов и сложных пользовательских фильтров, безопасные дефолты.

Сравнение по ключевым критериям:

| Критерий | Envoy | Linkerd Proxy |
| :--- | :--- | :--- |
| **Конфигурация** | xDS, богатая модель | Контроллер + CRD, минимум ручных настроек |
| **Протоколы** | HTTP/1–3, gRPC, TCP/UDP | HTTP/1–2, gRPC, TCP |
| **Расширяемость** | Фильтры, WASM | Ограниченная, без плагинов |
| **Нагрузка** | Выше, гибкость | Ниже, минимализм |
| **mTLS** | Политики Istio, SPIFFE-идентичности | Встроенный по умолчанию |

## Политики, безопасность и маршрутизация

Оба прокси реализуют mTLS для сквозного шифрования и идентификации сервисов. В Envoy идентичности и политики часто управляются через контрольную плоскость (например, Istio), применяются AuthorizationPolicy, DestinationRule, VirtualService. Linkerd использует собственные идентичности, а для поведенческих характеристик маршрутов применяет ServiceProfile, транслируемый в прокси через контроллер.

Поведение при сбоях включает ретраи с джиттером, таймауты, circuit breaking и outlier detection. В Envoy эти механизмы богаче и тоньше настраиваются; в Linkerd — проще, но покрывают типовые сценарии деградации.

## Наблюдаемость и отладка

### Envoy:

-   Метрики и трассировка через встроенные статистики и экспортеры.
-   Доступ к административному интерфейсу и диагностике.
-   Детальные access-logs и поддержка заголовков трассировки.

### Linkerd:

-   Метрики из коробки (latency, success rate, RPS), диаграммы golden signals.
-   Диагностические инструменты tap и top для наблюдения за трафиком.
-   Минимум конфигурации, акцент на безопасные стандартные метрики.

Примеры диагностики:

```bash
# Envoy admin (внутри sidecar-контейнера)
curl http://127.0.0.1:15000/stats
curl http://127.0.0.1:15000/clusters
```

```bash
# Linkerd наблюдение
linkerd stat deploy -n app
linkerd tap deploy/backend -n app
```

## Примеры конфигурации

Автовпрыск sidecar в Kubernetes:

```bash
# Istio (метка на namespace)
kubectl label namespace app istio-injection=enabled
```

```yaml
# Linkerd (аннотация на Pod/Deployment)
metadata:
  annotations:
    linkerd.io/inject: enabled
```

Минимальный статический Envoy bootstrap (для понимания структуры):

```yaml
static_resources:
  listeners:
  - name: inbound-http
    address: { socket_address: { address: 0.0.0.0, port_value: 15006 } }
    filter_chains:
    - filters:
      - name: envoy.filters.network.http_connection_manager
        typed_config:
          stat_prefix: inbound_http
          route_config:
            name: local_route
            virtual_hosts:
            - name: app
              domains: ["*"]
              routes:
              - match: { prefix: "/" }
                route: { cluster: local_service }
          http_filters:
          - name: envoy.filters.http.router
  clusters:
  - name: local_service
    connect_timeout: 1s
    type: STATIC
    load_assignment:
      cluster_name: local_service
      endpoints:
      - lb_endpoints:
        - endpoint: { address: { socket_address: { address: 127.0.0.1, port_value: 8080 } } }
```

ServiceProfile для Linkerd с маршрутными таймаутами:

```yaml
apiVersion: linkerd.io/v1alpha2
kind: ServiceProfile
metadata:
  name: backend.default.svc.cluster.local
  namespace: default
spec:
  routes:
  - name: GET /api/v1/items
    condition:
      method: GET
      pathRegex: /api/v1/items
    isRetryable: true
    timeout: 2s
```
