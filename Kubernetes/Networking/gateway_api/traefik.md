# Traefik — реализация Gateway API

## Определения

**Traefik** — современный обратный прокси-сервер и балансировщик нагрузки с открытым исходным кодом, который поддерживает спецификацию Gateway API для управления трафиком в Kubernetes.

**Kubernetes Gateway Provider** — провайдер Traefik, предназначенный для отслеживания ресурсов Gateway API (`GatewayClass`, `Gateway`, `HTTPRoute`, `TLSRoute` и др.) и динамической настройки правил маршрутизации на их основе.

## Базовые концепции

### Особенности реализации
- **Двойной режим:** Traefik может одновременно работать как классический Ingress Controller и как Gateway API Controller.
- **Direct Pod Targeting:** По умолчанию Traefik отправляет трафик напрямую на IP-адреса подов (endpoints), минуя стандартные Kubernetes Service. Это снижает задержки и накладные расходы на сетевую обработку.
- **Автоматизация:** При установке контроллер может автоматически создавать `GatewayClass` с именем `traefik`.

### Установка и активация
Для использования функций Gateway API необходимо включить соответствующий провайдер в конфигурации Traefik (например, через Helm `values.yaml`):

```yaml
providers:
  kubernetesGateway:
    enabled: true  # Активация поддержки Gateway API
  ingressClass:
    enabled: false  # Опциональное отключение классического Ingress
gateway:
  enabled: false  # Рекомендуется создавать ресурсы Gateway вручную для контроля
```

## Практические сценарии

### Настройка шлюза (Gateway)

Ресурс `Gateway` определяет точки входа трафика (Listeners) и привязку к контроллеру через `GatewayClass`.

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: traefik-gateway
  namespace: sample
spec:
  gatewayClassName: traefik
  listeners:
  - name: web
    protocol: HTTP
    port: 80
    allowedRoutes:
      namespaces:
        from: Same  # Разрешить маршруты только из того же namespace
  - name: websecure
    protocol: HTTPS
    port: 443
    tls:
      mode: Terminate
      certificateRefs:
      - name: sample-tls
        namespace: sample  # Secret может находиться в другом namespace
```

**Особенности настройки:**
- `hostname` в HTTP-слушателе (`listener`) не обязателен; маршрутизация может определяться на уровне `HTTPRoute`.
- Для HTTPS-слушателя `hostname` является обязательным полем.
- В режиме `Terminate` SSL-трафик расшифровывается на шлюзе и передается бэкенду по HTTP.
- В отличие от Ingress, `Secret` с TLS-сертификатом может находиться в другом пространстве имен (при наличии соответствующих разрешений `ReferenceGrant`).

### Настройка маршрутизации (HTTPRoute)

`HTTPRoute` связывает запросы по определенным критериям (хост, путь) с конкретными сервисами.

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: sample-http
  namespace: sample
spec:
  parentRefs:
  - name: traefik-gateway
    sectionName: web
  hostnames:
  - app.example.com
  rules:
  - matches:
    - path:
        type: PathPrefix
        value: /api
    backendRefs:
    - name: backend-service
      port: 80
```

**Ключевые моменты:**
- `HTTPRoute` может располагаться в любом пространстве имен кластера.
- Маршрут может ссылаться на сервисы (`backendRefs`), находящиеся в других пространствах имен.

## Дополнительная информация

**Преимущества использования Traefik с Gateway API:**
- Унифицированное управление трафиком через стандартные ресурсы.
- Встроенная поддержка Service Discovery и динамического обновления конфигурации.
- Гибкая работа с TLS-сертификатами.

**См. также:**
- [Концепции Gateway API](./definitions.md) — базовые определения и преимущества стандарта
- [Envoy Gateway](./envoy_gateway.md) — альтернативная реализация Gateway API
- [Интеграция с cert-manager](../../ToolsUtilities/cert_manager/LetsEncrypt/letsencrypt_scenarios.md) — автоматизация TLS

**Родительская тема:** [Gateway API](./definitions.md)
