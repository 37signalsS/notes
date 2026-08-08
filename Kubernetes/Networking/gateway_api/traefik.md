# Traefik — реализация Gateway API

## Определения

**Traefik (v3.3+)** — современный облачно-ориентированный обратный прокси-сервер и балансировщик нагрузки, обеспечивающий нативную поддержку спецификации Kubernetes Gateway API (v1.2+). Traefik является одной из наиболее популярных реализаций Gateway API благодаря своей простоте, автоматическому обнаружению сервисов и встроенной поддержке TLS (ACME).

**Kubernetes Gateway Provider** — встроенный компонент Traefik, который отслеживает ресурсы Gateway API в кластере и динамически генерирует правила маршрутизации. В отличие от традиционного Ingress-контроллера, Traefik в режиме Gateway API использует более гибкую ролевую модель разделения ответственности.

## Базовые концепции

### Особенности реализации

- **Direct Pod Targeting:** Traefik по умолчанию направляет трафик напрямую на IP-адреса подов (Endpoints), минуя виртуальный IP сервиса и `kube-proxy`. Это снижает задержки и позволяет реализовать более точные алгоритмы балансировки (например, EWMA).
- **Поддержка спецификации GAMMA:** Traefik v3 поддерживает управление трафиком внутри кластера (Service Mesh). Это позволяет использовать `HTTPRoute` с `parentRef`, указывающим на `Service`, для реализации канареечных релизов и зеркалирования трафика East-West.
- **Middleware и Filters:** Traefik интегрирует свои мощные Middleware (RateLimit, Circuit Breaker, Auth) через стандартный механизм `filters` в `HTTPRoute`. Для специфичных настроек, не покрытых стандартом, используется `ExtensionRef`.
- **Конвергенция конфигураций:** Traefik может одновременно обрабатывать ресурсы Ingress, Gateway API и свои собственные CRD (IngressRoute), обеспечивая плавную миграцию.

### Установка и активация

Для использования Gateway API необходимо предварительно установить CRD (версии v1.2.0+ для полной поддержки Traefik v3.3+).

В конфигурации Traefik (через Helm `values.yaml`) активация провайдера выглядит следующим образом:

```yaml
providers:
  kubernetesGateway:
    enabled: true
    experimentalChannel: true # Включает поддержку TCPRoute, UDPRoute и GRPCRoute
    statusAddress:
      service:
        name: traefik
        namespace: traefik
```

## Практические сценарии

### Настройка инфраструктуры (GatewayClass и Gateway)

`GatewayClass` объявляет Traefik контроллером, а `Gateway` описывает физические точки входа.

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: GatewayClass
metadata:
  name: traefik
spec:
  controllerName: traefik.io/gateway-controller
---
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: external-gw
  namespace: traefik
spec:
  gatewayClassName: traefik
  listeners:
  - name: https
    protocol: HTTPS
    port: 443
    tls:
      mode: Terminate
      certificateRefs:
      - name: wildcard-example-com
    allowedRoutes:
      namespaces:
        from: All
```

### Расширенная маршрутизация с Middleware

Пример использования Traefik Middleware через `ExtensionRef` для ограничения скорости (Rate Limiting).

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: api-route
  namespace: prod
spec:
  parentRefs:
  - name: external-gw
    namespace: traefik
  rules:
  - matches:
    - path: { type: PathPrefix, value: /v1 }
    filters:
    - type: ExtensionRef
      extensionRef:
        group: traefik.io
        kind: Middleware
        name: global-ratelimit
    backendRefs:
    - name: api-service
      port: 8080
```

### L4 Маршрутизация (TCP и TLS Passthrough)

Traefik v3 поддерживает маршрутизацию без дешифрования трафика.

**Пример TLSRoute (Passthrough):**
```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: TLSRoute
metadata:
  name: db-tls-passthrough
spec:
  parentRefs:
  - name: external-gw
    sectionName: tls-passthrough-port
  hostnames:
  - "db.example.com"
  rules:
  - backendRefs:
    - name: postgres-service
      port: 5432
```

### Поддержка gRPC

Для gRPC трафика Traefik предоставляет нативную маршрутизацию на уровне методов.

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: GRPCRoute
metadata:
  name: grpc-app
spec:
  parentRefs:
  - name: external-gw
  rules:
  - matches:
    - method:
        service: com.example.UserService
        method: GetUser
    backendRefs:
    - name: user-service
      port: 9000
```

## Дополнительная информация

### Наблюдаемость (Observability)

Traefik v3 глубоко интегрирован с инструментами мониторинга:
- **Метрики:** Встроенная поддержка Prometheus и OpenTelemetry. Метрики включают статистику по Gateway, Route и Backend.
- **Трассировка:** Поддержка Jaeger, Zipkin и OTLP для анализа сквозного прохождения запросов.
- **Access Logs:** Возможность записи логов в JSON-формате для последующего анализа в ELK/Loki.

### Отладка и диагностика

1. **Dashboard:** Traefik предоставляет веб-интерфейс (порт 8080), где можно визуально проверить состояние Gateway и привязанных к ним маршрутов.
2. **Проверка статуса в K8s:** Gateway API ресурсы имеют секцию `status`, которая содержит детальную информацию о причинах ошибок (например, `ConflictingListeners` или `InvalidBackendRef`).
   ```bash
   kubectl describe gateway external-gw -n traefik
   ```
3. **Логи контроллера:** При проблемах с обновлением конфигурации следует искать ошибки с префиксом `providerName: kubernetesgateway` в логах пода Traefik.

### См. также

- [Концепции Gateway API](./definitions.md) — базовые определения и преимущества стандарта.
- [L4-маршрутизация — TCPRoute и UDPRoute](./layer4_routing.md) — детали транспортного уровня.
- [Обзор Traefik](../../WebServers/Traefik/traefik_overview.md) — архитектура и общие возможности прокси.
- [Интеграция с cert-manager](../../ToolsUtilities/cert_manager/LetsEncrypt/letsencrypt_scenarios.md) — автоматизация TLS сертификатов.

**Родительская тема:** [Gateway API](./definitions.md)
