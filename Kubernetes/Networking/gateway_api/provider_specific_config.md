# Провайдер-специфичная конфигурация Gateway API

**Надёжность:** 10 (SSoT + Спецификация v1.5 / GEP-713 / Envoy Gateway v1.8)

## Определения

**Policy Attachment (GEP-713)** — архитектурный паттерн Gateway API, позволяющий расширять возможности шлюзов (таймауты, безопасность, лимиты) через специализированные "мета-ресурсы" (политики). Это избавляет от необходимости использовать хаотичные аннотации.

**Direct Policy Attachment** — модель прикрепления политики, влияющая только на конкретный целевой объект (например, `BackendTLSPolicy` для конкретного `Service`). Это наиболее стабильный и предсказуемый метод.

**Inherited Policy Attachment** — модель, при которой настройки политики "наследуются" вниз по иерархии (например, от `Gateway` ко всем его `HTTPRoute`). Поддерживает концепции **Defaults** (значения по умолчанию) и **Overrides** (принудительные переопределения).

**TargetRef** — типизированная ссылка в манифесте политики, указывающая на целевой ресурс (Gateway, HTTPRoute или Service), к которому применяется данная конфигурация.

## Базовые концепции

### Проблема тонкой настройки

Стандартные ресурсы Gateway API (например, `HTTPRoute`) намеренно ограничены общими параметрами для обеспечения переносимости. Специфические функции контроллеров вынесены в политики:

- **Безопасность:** JWT, OIDC, OAuth2, аутентификация по клиентским сертификатам (mTLS).
- **Отказоустойчивость:** Тонкая настройка ретриев, таймаутов и автоматическое размыкание цепи (Circuit Breaking).
- **Управление трафиком:** Сложные алгоритмы балансировки (Maglev, Ring Hash), ограничение полосы пропускания (Bandwidth Limiting).

### Иерархия политик

В 2026 году соблюдается чёткий приоритет применения политик (от наиболее специфичных к общим):
1. **Route-level Policy:** Максимальный приоритет, действует на конкретный путь/хост.
2. **Gateway-level Policy:** Влияет на весь трафик шлюза.
3. **Namespace-level Policy:** Действует на все ресурсы внутри пространства имён (обычно для задания Default-значений).

## Практические сценарии (на примере Envoy Gateway v1.8)

### Тонкая настройка устойчивости (BackendTrafficPolicy)

Политика настраивает поведение при взаимодействии с бэкенд-сервисом.

```yaml
apiVersion: gateway.envoyproxy.io/v1alpha1
kind: BackendTrafficPolicy
metadata:
  name: api-resiliency-policy
  namespace: app-prod
spec:
  targetRef:
    group: gateway.networking.k8s.io
    kind: HTTPRoute
    name: main-api-route
  circuitBreaker:
    maxConnections: 1000
    maxPendingRequests: 100
  retry:
    numRetries: 3
    retryOn: [5xx, gateway-error]
    perTryTimeout: 2s
```

### Безопасность и JWT (SecurityPolicy)

Политика управляет аутентификацией и авторизацией на уровне шлюза.

```yaml
apiVersion: gateway.envoyproxy.io/v1alpha1
kind: SecurityPolicy
metadata:
  name: global-security
  namespace: gateway-system
spec:
  targetRef:
    group: gateway.networking.k8s.io
    kind: Gateway
    name: external-gateway
  jwt:
    providers:
    - name: auth0
      issuer: https://auth.example.com/
      audiences: ["api-v1"]
      remoteJWKS:
        uri: https://auth.example.com/.well-known/jwks.json
```

### Проверка "Эффективной политики" (Status)

Для отладки в 2026 году используется анализ статусов. Поле `Enforced: True` подтверждает, что политика активно управляет трафиком.

```bash
# Проверка применения политики
kubectl describe backendtrafficpolicy api-resiliency-policy

# Ожидаемый статус:
# status:
#   conditions:
#   - status: "True"
#     type: Accepted
#   - status: "True"
#     type: Programmed
```

## Дополнительная информация

### Рекомендации (Best Practices)

- **Минимизация Overrides:** Старайтесь использовать `Defaults` на уровне неймспейса и уточнять их на уровне маршрутов, избегая жестких глобальных переопределений, которые сложно отлаживать.
- **Изоляция политик:** Группируйте политики по функциональному признаку (например, одна политика для Auth, другая для QoS).
- **Использование gwctl:** Для визуализации того, какие политики применяются к конкретному `HTTPRoute`, используйте утилиту `gwctl` (входит в стандартный набор инструментов Gateway API).

**См. также:**

- [Определения Gateway API](./definitions.md) — базовые концепции стандарта
- [Envoy Gateway](./envoy_gateway.md) — особенности реализации EG v1.8
- [Traefik](./traefik.md) — альтернативный подход к расширению через Middleware

**Родительская тема:** [Gateway API](./definitions.md)
