# Gateway API Provider-Specific Configuration

## Определения

**Policy Attachment** — механизм Gateway API для расширения функциональности (rate limiting, authentication, WAF, circuit breaking) через отдельные ресурсы политик без загрязнения основного API маршрутизации.

**Provider-Specific Configuration** — конфигурация, специфичная для конкретной реализации Gateway API (Envoy, Traefik, Kong, облачные провайдеры). Возникает из-за того, что стандартные ресурсы не покрывают все возможные опции контроллеров.

**TargetRef** — поле в спецификации политики, указывающее на целевой ресурс Gateway API (Gateway, HTTPRoute, Service, Namespace).

## Базовые концепции

### Проблема тонкой настройки

Стандартные ресурсы `HTTPRoute`, `Gateway` не покрывают все возможные опции контроллеров: таймауты, лимиты, специфические алгоритмы балансировки, WAF-правила.

**Причины:**

- Gateway API — стандарт, а не реализация
- Разные провайдеры поддерживают разные наборы функций
- Специфичные функции (например, интеграция с облачными сервисами) требуют вендор-специфичных расширений

### Решение через Policy Attachment

Policy Attachment позволяет добавлять расширенные функции через отдельные ресурсы:

**Принципы:**

1. **Separation of concerns:** Маршрутизация в `HTTPRoute`, расширенные функции в политиках.
2. **Vendor extensibility:** Реализации шлюзов могут добавлять кастомные политики.
3. **Hierarchy and precedence:** Политики применяются на разных уровнях с чёткими правилами приоритета.

**Точки прикрепления (Attachment Points):** `Gateway`, `HTTPRoute`, `Service`, `Namespace`.

**Приоритет (Precedence):** `Route-level` > `Gateway-level` > `Namespace-level`.

### Статус на 2026 год

**Проблема:** Отсутствие единого стандарта Policy Attachment. Провайдеры реализуют политики через собственные CRD или provider-specific annotations, что создаёт конфигурационный дрейф и снижает переносимость.

**Реальность:** Некоторые провайдеры поддерживают Policy Attachment в статусе beta, другие игнорируют, требуя fallback к аннотациям или кастомным ресурсам.

## Практические сценарии

### Rate Limiting (Envoy Gateway)

```yaml
apiVersion: gateway.envoyproxy.io/v1alpha1
kind: BackendTrafficPolicy
metadata:
  name: rate-limit-policy
spec:
  targetRef:
    group: gateway.networking.k8s.io
    kind: HTTPRoute
    name: api-route
  rateLimit:
    type: Global
    global:
      rules:
      - limit:
          requests: 100
          unit: Minute
```

### Authentication (JWT)

```yaml
apiVersion: gateway.envoyproxy.io/v1alpha1
kind: SecurityPolicy
spec:
  targetRef:
    group: gateway.networking.k8s.io
    kind: HTTPRoute
    name: authenticated-api-route
  jwt:
    providers:
    - name: auth0
      issuer: https://example.auth0.com/
```

### Проверка статуса политики

```bash
kubectl get backendtrafficpolicy rate-limit-policy -o yaml
```

Поля для проверки: `status.conditions` с типами `Accepted`, `Enforced`.

## Дополнительная информация

**Стратегия миграции:** Изолировать конфигурацию Gateway API YAML от провайдер-специфичных политик и аннотаций. Это упрощает смену провайдера и снижает риск vendor lock-in.

**Рекомендация:** Для greenfield-проектов использовать только стабильные ресурсы v1 (Gateway, HTTPRoute). Использование beta/experimental-ресурсов трактовать как известный риск рефакторинга.

**Best Practices:**

- Одна политика — одна задача (auth, rate limit).
- Документирование правил приоритета.
- Валидация существования целевых ресурсов (targetRef).
- Обновление статуса политики (Accepted/Enforced).
- Версионирование API политик.

**Troubleshooting:**

- Проверка неймспейса и имени в `targetRef`.
- Анализ логов контроллера: `kubectl logs -n gateway-system -l app=policy-controller`.
- Верификация через curl (заголовки rate limit).

Концепции Gateway API: [Определения](./definitions.md).

Реализации: [Envoy Gateway](./envoy_gateway.md), [Traefik](./traefik.md).

Официальная документация: [Gateway API Policy Attachment](https://gateway-api.sigs.k8s.io/concepts/api-overview/#policy-attachment).
