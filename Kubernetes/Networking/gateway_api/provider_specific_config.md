# Провайдер-специфичная конфигурация Gateway API

## Определения

**Policy Attachment (GEP-713)** — архитектурный паттерн Gateway API, позволяющий расширять возможности шлюзов (таймауты, безопасность, лимиты) через специализированные "мета-ресурсы" (политики). Это избавляет от необходимости использовать хаотичные аннотации.

**Direct Policy Attachment** — модель прикрепления политики, влияющая только на конкретный целевой объект (например, `BackendTLSPolicy` для конкретного `Service`). Это наиболее стабильный и предсказуемый метод.

**Inherited Policy Attachment** — модель, при которой настройки политики "наследуются" вниз по иерархии (например, от `Gateway` ко всем его `HTTPRoute`). Поддерживает концепции **Defaults** (значения по умолчанию) и **Overrides** (принудительные переопределения).

**TargetRef** — типизированная ссылка в манифесте политики, указывающая на целевой ресурс (Gateway, HTTPRoute или Service), к которому применяется данная конфигурация.

## Предварительные требования

### Компоненты и версии

| Компонент | Минимальная версия | Проверка |
| :--- | :--- | :--- |
| Kubernetes | 1.24+ | `kubectl version --short` |
| Gateway API CRD | v1.0.0+ | `kubectl get crd gatewayclasses.gateway.networking.k8s.io` |
| Контроллер шлюза | Зависит от реализации | `kubectl get pods -n <gateway-namespace>` |
| kubectl | 1.24+ | `kubectl version --client --short` |

### Проверка установки Gateway API

```bash
# Проверка наличия базовых CRD Gateway API
kubectl get crd | grep gateway.networking.k8s.io
# → gatewayclasses.gateway.networking.k8s.io
# → gateways.gateway.networking.k8s.io
# → httproutes.gateway.networking.k8s.io
# → referencegrants.gateway.networking.k8s.io
```

### Проверка поддержки Policy Attachment контроллером

```bash
# Для Envoy Gateway — проверка наличия CRD политик
kubectl get crd | grep -E "(backendtrafficpolic|securitypolic|clienttrafficpolic)"
# → backendtrafficpolicies.gateway.envoyproxy.io
# → securitypolicies.gateway.envoyproxy.io
# → clienttrafficpolicies.gateway.envoyproxy.io

# Для KGateway
kubectl get crd | grep kgateway.dev
# → backendtrafficpolicies.gateway.kgateway.dev
# → securitypolicies.gateway.kgateway.dev
```

### Требования к правам RBAC

Для работы с политиками необходимы следующие права:

- `get`, `list`, `watch` — для ресурсов `Gateway`, `HTTPRoute`, `GatewayClass`
- `get`, `list`, `watch` — для CRD политик (например, `backendtrafficpolicies`)
- `get` — для `ReferenceGrant` (при кросс-namespace ссылках)

## Базовые концепции

### Проблема тонкой настройки

Стандартные ресурсы Gateway API (например, `HTTPRoute`) намеренно ограничены общими параметрами для обеспечения переносимости. Специфические функции контроллеров вынесены в политики:

- **Безопасность:** JWT, OIDC, OAuth2, аутентификация по клиентским сертификатам (mTLS).
- **Отказоустойчивость:** Тонкая настройка ретриев, таймаутов и автоматическое размыкание цепи (Circuit Breaking).
- **Управление трафиком:** Сложные алгоритмы балансировки (Maglev, Ring Hash), ограничение полосы пропускания (Bandwidth Limiting).

### Иерархия политик

Соблюдается чёткий приоритет применения политик (от наиболее специфичных к общим):

1. **Route-level Policy:** Максимальный приоритет, действует на конкретный путь/хост.
2. **Gateway-level Policy:** Влияет на весь трафик шлюза.
3. **Namespace-level Policy:** Действует на все ресурсы внутри пространства имён (обычно для задания Default-значений).

### Сравнение моделей прикрепления

| Характеристика | Direct Policy | Inherited Policy |
| :--- | :--- | :--- |
| **Область действия** | Один конкретный ресурс | Иерархия ресурсов |
| **Приоритет** | Высокий (явная привязка) | Зависит от уровня |
| **Гибкость** | Точечная настройка | Массовое применение |
| **Предсказуемость** | Высокая | Средняя (зависит от наследования) |
| **Типичное использование** | BackendTLSPolicy, BackendTrafficPolicy | Глобальные политики безопасности |

## Практические сценарии

### Тонкая настройка устойчивости (BackendTrafficPolicy)

Политика настраивает поведение при взаимодействии с бэкенд-сервисом: управление соединениями, ретрии, circuit breaker.

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

**Валидация:**

```bash
# Применение политики
kubectl apply -f backend-traffic-policy.yaml

# Проверка статуса
kubectl describe backendtrafficpolicy api-resiliency-policy -n app-prod
# → Status:
# →   Conditions:
# →     Type:     Accepted
# →     Status:   True

# Проверка что политика привязана к маршруту
kubectl get httproute main-api-route -n app-prod -o yaml | grep -A5 "policies"
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

**Валидация:**

```bash
# Применение политики
kubectl apply -f security-policy.yaml

# Проверка статуса
kubectl describe securitypolicy global-security -n gateway-system
# → Status:
# →   Conditions:
# →     Type:     Accepted
# →     Status:   True

# Проверка работы JWT (запрос без токена должен вернуть 401)
curl -i https://api.example.com/protected-endpoint
# → HTTP/1.1 401 Unauthorized

# Проверка с валидным токеном
curl -i -H "Authorization: Bearer $JWT_TOKEN" https://api.example.com/protected-endpoint
# → HTTP/1.1 200 OK
```

### Настройка CORS через SecurityPolicy

```yaml
apiVersion: gateway.envoyproxy.io/v1alpha1
kind: SecurityPolicy
metadata:
  name: cors-policy
  namespace: gateway-system
spec:
  targetRef:
    group: gateway.networking.k8s.io
    kind: Gateway
    name: external-gateway
  cors:
    allowOrigins:
    - "https://app.example.com"
    - "https://admin.example.com"
    allowMethods:
    - GET
    - POST
    - PUT
    - DELETE
    allowHeaders:
    - Authorization
    - Content-Type
    - X-Request-ID
    maxAge: "86400s"
```

**Валидация:**

```bash
# Проверка CORS-заголовков
curl -I -H "Origin: https://app.example.com" \
  -H "Access-Control-Request-Method: GET" \
  -X OPTIONS https://api.example.com/resource
# → Access-Control-Allow-Origin: https://app.example.com
# → Access-Control-Allow-Methods: GET, POST, PUT, DELETE
# → Access-Control-Max-Age: 86400

# Проверка что невалидный Origin отклоняется
curl -I -H "Origin: https://evil.example.com" \
  -H "Access-Control-Request-Method: GET" \
  -X OPTIONS https://api.example.com/resource
# → (нет Access-Control-Allow-Origin)
```

### Настройка ClientTrafficPolicy (управление клиентским трафиком)

```yaml
apiVersion: gateway.envoyproxy.io/v1alpha1
kind: ClientTrafficPolicy
metadata:
  name: client-tcp-settings
  namespace: gateway-system
spec:
  targetRef:
    group: gateway.networking.k8s.io
    kind: Gateway
    name: external-gateway
  tcp:
    keepalive:
      probes: 5
      interval: 60s
      idleTime: 300s
  http:
    http2:
      initialConnectionWindowSize: "1MB"
      initialStreamWindowSize: "64KB"
```

**Валидация:**

```bash
# Применение политики
kubectl apply -f client-traffic-policy.yaml

# Проверка статуса
kubectl describe clienttrafficpolicy client-tcp-settings -n gateway-system
# → Status:
# →   Conditions:
# →     Type:     Accepted
# →     Status:   True

# Проверка настроек TCP keepalive (через Envoy admin interface)
kubectl port-forward -n gateway-system pod/<envoy-pod> 19000:19000
curl http://localhost:19000/config_dump | jq '.configs[].bootstrap.static_resources.clusters[] | .upstream_connection_config'
```

### Проверка "Эффективной политики" (Status)

Для отладки используется анализ статусов. Поле `Accepted: True` подтверждает, что политика активно управляет трафиком.

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

# Массовая проверка всех политик в namespace
kubectl get backendtrafficpolicy,securitypolicy,clienttrafficpolicy -n app-prod
# → NAME                        STATUS    AGE
# → api-resiliency-policy       Accepted  5m
```

### Отладка с использованием gwctl

```bash
# Установка gwctl (если не установлен)
# Скачать с https://gateway-api.sigs.k8s.io/guides/gwctl/

# Просмотр политик применяемых к конкретному HTTPRoute
gwctl describe httproute main-api-route -n app-prod
# → HTTPRoute main-api-route
# →   BackendTrafficPolicy: api-resiliency-policy (Accepted)
# →   SecurityPolicy: global-security (Accepted)

# Просмотр всей иерархии Gateway с политиками
gwctl describe gateway external-gateway -n gateway-system
```

## Troubleshooting

### Типичные ошибки и решения

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `Accepted: False` | Неверный `targetRef` или целевой ресурс не существует | Проверить существование целевого ресурса и корректность `group`, `kind`, `name` в `targetRef` |
| `Programmed: False` | Контроллер не может применить политику | Проверить логи контроллера: `kubectl logs -n <namespace> <controller-pod>` |
| `InvalidParameter` | Недопустимые значения в спецификации политики | Проверить CRD-схему: `kubectl explain backendtrafficpolicy.spec` |
| `Conflicted` | Конфликт между Direct и Inherited политиками | Определить приоритет: Route-level > Gateway-level > Namespace-level |
| `Forbidden` | Отсутствует ReferenceGrant для кросс-namespace привязки | Создать ReferenceGrant в namespace целевого ресурса |
| `TargetNotFound` | Целевой ресурс удалён или недоступен | Проверить статус целевого ресурса: `kubectl get <kind> <name> -n <namespace>` |
| `PermissionDenied` | Недостаточно прав RBAC у ServiceAccount контроллера | Проверить ClusterRole контроллера на наличие прав для целевых ресурсов |

### Диагностика проблем

```bash
# Проверка всех политик в кластере
kubectl get backendtrafficpolicy,securitypolicy,clienttrafficpolicy -A

# Детальная информация о статусе политики
kubectl get backendtrafficpolicy <name> -n <namespace> -o yaml

# Просмотр событий политики
kubectl describe backendtrafficpolicy <name> -n <namespace>
# Обратить внимание на секцию Events

# Проверка логов контроллера (Envoy Gateway)
kubectl logs -n envoy-gateway-system -l control-plane=envoy-gateway-controller

# Проверка логов контроллера (KGateway)
kubectl logs -n kgateway-system -l app=kgateway

# Проверка что политика применилась к Envoy-конфигурации
kubectl port-forward -n <namespace> pod/<envoy-pod> 19000:19000
curl http://localhost:19000/config_dump | jq '.configs[].http_connection_manager'
```

### Процедура отката

```bash
# Удаление конкретной политики
kubectl delete backendtrafficpolicy <name> -n <namespace>

# Массовое удаление всех политик определённого типа
kubectl delete backendtrafficpolicy --all -n <namespace>

# Проверка что политика удалена и конфигурация восстановлена
kubectl describe gateway <gateway-name> -n <namespace>
curl -i https://api.example.com/endpoint
```

## Дополнительная информация

### Рекомендации (Best Practices)

**Структурирование политик:**

- **Минимизация Overrides:** Старайтесь использовать `Defaults` на уровне неймспейса и уточнять их на уровне маршрутов, избегая жестких глобальных переопределений, которые сложно отлаживать.
- **Изоляция политик:** Группируйте политики по функциональному признаку (например, одна политика для Auth, другая для QoS).
- **Использование Direct Policy:** Для критичных настроек предпочитайте Direct Policy Attachment — это обеспечивает явную привязку и предсказуемое поведение.

**Безопасность:**

- **ReferenceGrant:** Всегда создавайте `ReferenceGrant` для кросс-namespace привязок — это предотвращает несанкционированный доступ к политикам.
- **Least Privilege:** Ограничивайте права политик минимально необходимым набором действий.
- **Аудит:** Регулярно проверяйте какие политики применены к ресурсам с помощью `gwctl`.

**Производительность:**

- **Circuit Breaker:** Настраивайте `maxConnections` и `maxPendingRequests` в соответствии с возможностями бэкендов.
- **Retry Budgets:** Используйте `retryBudget` для предотвращения лавины ретриев при деградации бэкенда.
- **Таймауты:** Всегда задавайте `perTryTimeout` для ограничения времени ожидания повторных попыток.

**Мониторинг и отладка:**

- **Использование gwctl:** Для визуализации того, какие политики применяются к конкретному `HTTPRoute`, используйте утилиту `gwctl` (входит в стандартный набор инструментов Gateway API).
- **Статусы:** Регулярно проверяйте `status.conditions` политик для выявления проблем.
- **Метрики:** Включите экспорт метрик политик в Prometheus для мониторинга в реальном времени.

**Миграция:**

- **Постепенное внедрение:** Начинайте с Direct Policy для критичных сервисов, затем расширяйте на другие компоненты.
- **Shadow Mode:** Используйте `shadowMode: true` для тестирования новых политик без влияния на трафик (доступно в Envoy Gateway).

### Ограничения и особенности

- **Совместимость:** Не все контроллеры Gateway API поддерживают все типы политик — проверяйте документацию конкретной реализации.
- **Валидация:** CRD-схемы политик валидируют базовые параметры, но семантические ошибки (например, конфликт таймаутов) могут быть обнаружены только во время выполнения.
- **Производительность:** Каждая политика увеличивает размер конфигурации Envoy — учитывайте это при большом количестве политик.

**См. также:**

- [Определения Gateway API](./definitions.md) — базовые концепции стандарта
- [Envoy Gateway](./envoy_gateway.md) — особенности реализации EG с примерами политик
- [Gateway API — Ресурсы (CRD)](./resources.md) — полное описание ресурсов включая BackendTLSPolicy

**Родительская тема:** [Gateway API](./definitions.md)
