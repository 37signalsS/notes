# Consul API Gateway

# Определения

**Consul API Gateway** — это специализированное решение для управления входящим трафиком (North-South), которое заменяет устаревший Ingress Gateway. Оно построено на базе **Envoy** и реализует спецификацию **Kubernetes Gateway API**, обеспечивая бесшовную интеграцию внешнего мира с Consul Service Mesh.

В отличие от классического Ingress, API Gateway использует ролевую модель управления, разделяя ответственность между администраторами инфраструктуры (создание шлюзов) и разработчиками приложений (определение маршрутов).

# Архитектура и интеграция с Kubernetes

API Gateway работает как контроллер внутри Kubernetes, который отслеживает стандартные ресурсы Gateway API и транслирует их в конфигурацию прокси-серверов Envoy.

## Ключевые ресурсы (CRD)

| Ресурс | Описание | Зона ответственности |
| :--- | :--- | :--- |
| **GatewayClass** | Шаблон для создания шлюзов (тип `consul`). | Админ инфраструктуры |
| **Gateway** | Физическая точка входа (IP, порты, TLS-сертификаты). | Оператор кластера |
| **HTTPRoute** | Правила маршрутизации (пути, заголовки, фильтры). | Разработчик приложения |
| **ReferenceGrant** | Разрешение на использование ресурсов из других неймсейсов. | Секьюрити админ |

## Механизм работы
1.  **Контроллер** обнаруживает новый ресурс `Gateway`.
2.  Consul развертывает **Deployment** с Envoy-прокси и сервис типа `LoadBalancer`.
3.  Разработчик создает `HTTPRoute`, привязывая его к `Gateway`.
4.  Envoy-прокси автоматически получает конфигурацию и направляет внешний трафик в Service Mesh, используя **mTLS** для общения с внутренними сервисами.

# Практические сценарии

## 1. Включение API Gateway (Helm)

API Gateway должен быть включен в `values.yaml` чарта `consul-k8s`.

```yaml
apiGateway:
  enabled: true
  managedGatewayClass:
    enabled: true
    serviceType: LoadBalancer
```

## 2. Создание шлюза (Gateway)

Этот манифест создает точку входа, слушающую HTTPS на порту 443.

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: public-gateway
  namespace: consul
spec:
  gatewayClassName: consul # Ссылка на GatewayClass
  listeners:
  - name: https
    protocol: HTTPS
    port: 443
    hostname: "api.example.com"
    tls:
      mode: Terminate
      certificateRefs:
      - name: example-com-cert # Ссылка на Secret с сертификатом
    allowedRoutes:
      namespaces:
        from: All
```

## 3. Маршрутизация с разделением трафика (Canary)

Пример `HTTPRoute`, который направляет 90% трафика на стабильную версию и 10% на новую.

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: api-route
  namespace: apps
spec:
  parentRefs:
  - name: public-gateway
    namespace: consul
  hostnames:
  - "api.example.com"
  rules:
  - matches:
    - path:
        type: PathPrefix
        value: /v1
    backendRefs:
    - name: service-stable
      port: 8080
      weight: 90
    - name: service-canary
      port: 8080
      weight: 10
```

# Продвинутые возможности (v1.20+)

- **Cross-namespace Routing**: Использование `ReferenceGrant` позволяет безопасно ссылаться на сервисы или секреты в разных неймсейсах Kubernetes.
- **TLS SDS (Secret Discovery Service)**: Поддержка динамического обновления сертификатов без перезагрузки подов прокси.
- **TCPRoute**: Возможность проксирования L4-трафика (например, для баз данных) с поддержкой TLS Passthrough.

# Устранение неполадок (Troubleshooting)

## Проверка статуса шлюза
Если трафик не проходит, проверьте статус ресурса `Gateway`:
```bash
kubectl get gateway public-gateway -n consul -o yaml
# Ищите секцию status.conditions. Должно быть Ready: True
```

## Проверка привязки маршрута
Убедитесь, что `HTTPRoute` успешно "принят" шлюзом:
```bash
kubectl get httproute api-route -n apps -o yaml
# В секции status.parents должно быть Accepted: True
```

## Логи контроллера
Если ресурсы не создаются, проверьте логи пода `consul-api-gateway-controller`:
```bash
kubectl logs -l app=consul-api-gateway-controller -n consul
```

# Дополнительная информация

- **[Consul Service Mesh](./consul_service_mesh.md)** — архитектура внутренней сети.
- **[Управление трафиком L7](./consul_service_mesh.md#управление-трафиком-l7-router-splitter-resolver)** — аналогичные механизмы внутри сетки.
- **[Kubernetes Gateway API](https://gateway-api.sigs.k8s.io/)** — официальная спецификация.
