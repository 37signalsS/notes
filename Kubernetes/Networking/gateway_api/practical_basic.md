# Gateway API — базовые сценарии

## Определения

**Gateway API** — современный стандарт управления трафиком в Kubernetes. Он предоставляет типобезопасный и ролевой интерфейс для настройки балансировщиков нагрузки. Основные концепции описаны в [Определениях](./definitions.md).

**HTTPRoute** — основной ресурс разработчика для описания правил маршрутизации HTTP-трафика (хосты, пути, фильтры).

**ReferenceGrant** — ресурс безопасности, разрешающий ссылки между namespace. Необходим для кросс-неймспейс маршрутизации (когда Gateway в одном namespace, а HTTPRoute или Service — в другом).

## Предварительные требования

- Kubernetes кластер версии 1.25+
- Gateway API CRD версии v1.6.0+
- Установленный контроллер Gateway API (Envoy Gateway, KGateway, Traefik, Cilium)
- Балансировщик нагрузки с поддержкой произвольных портов (MetalLB для bare-metal)
- Доступ к кластеру через `kubectl` с правами на создание ресурсов в целевых namespace

## Базовые концепции

### Цепочка взаимодействия ресурсов

Публикация приложения в 2026 году (после EOL Ingress-NGINX) требует настройки трёх уровней абстракции:

1. **GatewayClass** (Инфраструктура) — выбор реализации (Envoy Gateway, Traefik, Cilium).
2. **Gateway** (Сеть) — конфигурация портов (80, 443) и привязка IP.
3. **HTTPRoute** (Приложение) — логика распределения запросов по сервисам.

Детальное описание полей каждого ресурса приведено в разделе [Ресурсы (CRD)](./resources.md).

### Статусы ресурсов (Conditions)

Gateway API предоставляет детальную диагностику через `status.conditions`:

| Условие | Описание |
| :--- | :--- |
| **Accepted** | Ресурс синтаксически корректен и принят контроллером |
| **Programmed** | (только для Gateway) Инфраструктура шлюза успешно настроена |
| **ResolvedRefs** | Все зависимости (Service, ReferenceGrant) найдены и корректны |

## Практические сценарии

### Шаг 1: Определение класса шлюза (GatewayClass)

Создаётся администратором кластера один раз для всей инфраструктуры.

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: GatewayClass
metadata:
  name: external-envoy
spec:
  controllerName: "gateway.envoyproxy.io/gatewayclass-controller"
  description: "Стандартный внешний балансировщик на базе Envoy"
```

**Валидация:**
```bash
kubectl get gatewayclass external-envoy
# → NAME             CONTROLLER                                            AGE
# → external-envoy   gateway.envoyproxy.io/gatewayclass-controller         10s

kubectl describe gatewayclass external-envoy
# → Status:
# →   Conditions:
# →     Last Transition Time:  2026-09-01T18:00:00Z
# →     Reason:                Accepted
# →     Status:                True
# →     Type:                  Accepted
```

### Шаг 2: Настройка шлюза (Gateway)

Оператор инфраструктуры создаёт шлюз в системном пространстве имён (`infra-ns`).

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: public-gateway
  namespace: infra-ns
spec:
  gatewayClassName: external-envoy
  listeners:
  - name: http
    protocol: HTTP
    port: 80
    allowedRoutes:
      namespaces:
        from: All # Разрешает маршруты из любых пространств имён
```

**Валидация:**
```bash
kubectl get gateway public-gateway -n infra-ns
# → NAME             CLASS           ADDRESS        PROGRAMMED   AGE
# → public-gateway   external-envoy  192.168.1.100  True         2m

kubectl describe gateway public-gateway -n infra-ns
# → Status:
# →   Conditions:
# →     Reason:                Programmed
# →     Status:                True
# →     Type:                  Programmed
```

> **Примечание:** Поле `ADDRESS` заполняется после выделения IP балансировщиком нагрузки. Если значение пустое — проверьте конфигурацию MetalLB или аналога.

### Шаг 3: Безопасное подключение маршрута (ReferenceGrant)

Если сервис находится в другом пространстве имён, чем шлюз, необходимо разрешить шлюзу "видеть" бэкенды. Это критическое отличие от Ingress, повышающее безопасность.

**Сценарий:** Gateway в `infra-ns`, HTTPRoute и Service в `app-prod`. Для разрешения ссылки HTTPRoute на Gateway в другом namespace необходим ReferenceGrant.

```yaml
# В namespace infra-ns (где находится Gateway)
apiVersion: gateway.networking.k8s.io/v1beta1
kind: ReferenceGrant
metadata:
  name: allow-app-prod-routes
  namespace: infra-ns
spec:
  from:
  - group: gateway.networking.k8s.io
    kind: HTTPRoute
    namespace: app-prod
  to:
  - group: gateway.networking.k8s.io
    kind: Gateway
```

**Валидация:**
```bash
kubectl get referencegrant -n infra-ns
# → NAME                   AGE
# → allow-app-prod-routes  30s
```

### Шаг 4: Описание маршрутов приложения (HTTPRoute)

Разработчик разворачивает правила в своём пространстве имён.

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: web-api-route
  namespace: app-prod
spec:
  parentRefs:
  - name: public-gateway
    namespace: infra-ns
  hostnames:
  - "api.example.com"
  rules:
  - matches:
    - path: { type: PathPrefix, value: /v1 }
    backendRefs:
    - name: api-v1-service
      port: 8080
  - matches:
    - path: { type: PathPrefix, value: / }
    backendRefs:
    - name: frontend-service
      port: 80
```

**Валидация:**
```bash
kubectl get httproute web-api-route -n app-prod
# → NAME             HOSTNAMES           AGE
# → web-api-route    api.example.com     1m

kubectl describe httproute web-api-route -n app-prod
# → Status:
# →   Parents:
# →     Conditions:
# →       Reason:                Accepted
# →       Status:                True
# →       Type:                  Accepted
# →       Reason:                ResolvedRefs
# →       Status:                True
# →       Type:                  ResolvedRefs
```

**Проверка доступности сервиса:**
```bash
# Из пода контроллера проверить доступность бэкенда
kubectl exec -n infra-ns deploy/public-gateway -- curl -s http://api-v1-service.app-prod.svc.cluster.local:8080/health
# → {"status": "ok"}
```

## Механизм обработки трафика

После применения манифестов:

1. **Контроллер** (например, Envoy Gateway) динамически выделяет внешний IP через MetalLB или аналогичное решение.
2. **Запрос** (`api.example.com/v1/users`) попадает на балансировщик.
3. **Gateway** находит слушателя на порту 80 и проверяет права `HTTPRoute` в неймспейсе `app-prod`.
4. **HTTPRoute** сопоставляет путь `/v1` и направляет трафик напрямую на поды сервиса `api-v1-service`.

## Troubleshooting

### Типичные ошибки и решения

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `Accepted: False` на Gateway | Неверный `gatewayClassName` или контроллер не запущен | Проверить `kubectl get gatewayclass` и логи контроллера |
| `ResolvedRefs: False` на HTTPRoute | Отсутствует ReferenceGrant или неверная ссылка | Проверить `kubectl get referencegrant -A` и ссылки parentRefs/backendRefs |
| `Programmed: False` на Gateway | Балансировщик не смог выделить IP | Проверить логи контроллера и конфигурацию MetalLB |
| Трафик не доходит до бэкенда | Неправильные порты или имя сервиса | Проверить `kubectl get svc -n app-prod` и backendRefs |
| 502/503 ошибки | Поды не готовы или нет endpoints | Проверить `kubectl get endpoints -n app-prod` |

### Диагностика проблем

```bash
# Проверка всех Gateway API ресурсов
kubectl get gatewayclass,gateway,httproute -A

# Проверка статусов
kubectl get gateway -A -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.status.conditions[0].type}{"\t"}{.status.conditions[0].status}{"\n"}{end}'

# Проверка HTTPRoute
kubectl get httproute -A -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.status.parents[0].conditions[0].type}{"\t"}{.status.parents[0].conditions[0].status}{"\n"}{end}'

# Просмотр событий
kubectl get events -n infra-ns --field-selector reason=GatewayNotProgrammed
kubectl get events -n app-prod --field-selector reason=ResolvedRefsFailed

# Проверка логов контроллера
kubectl logs -n envoy-gateway-system -l control-plane=envoy-gateway-controller --tail=100
```

### Диагностика сети

```bash
# Проверка доступности бэкенда из пода контроллера
kubectl exec -n infra-ns deploy/public-gateway -- curl -v http://api-v1-service.app-prod.svc.cluster.local:8080

# Проверка DNS внутри кластера
kubectl exec -n infra-ns deploy/public-gateway -- nslookup api-v1-service.app-prod.svc.cluster.local

# Проверка endpoints
kubectl get endpoints -n app-prod
# → NAME               ENDPOINTS       AGE
# → api-v1-service     10.244.1.5:8080 5m
```

## Best Practices

### Организация инфраструктуры

1. **Используйте отдельные Gateway для разных сред:**
   - `prod-gateway` для production
   - `staging-gateway` для staging
   - Изолирует трафик и упрощает диагностику

2. **Централизуйте управление Gateway в системном namespace:**
   - Gateway в `infra-ns` или `gateway-system`
   - Разработчики создают HTTPRoute в своих namespace
   - Упрощает аудит и контроль доступа

3. **Ограничивайте доступ через `allowedRoutes`:**
   - Вместо `from: All` используйте `from: Selector` с метками namespace
   - Предотвращает случайное подключение маршрутов

### Безопасность

1. **Всегда используйте ReferenceGrant для cross-namespace ссылок:**
   - Указывайте конкретные namespace и типы ресурсов
   - Не используйте wildcard-разрешения

2. **Настройте HTTPS для production:**
   - Используйте TLS-терминацию на Gateway
   - Интегрируйте с cert-manager для автоматического обновления сертификатов

3. **Мониторинг статусов:**
   - Настройте алерты на изменения условий (Accepted, Programmed, ResolvedRefs)
   - Отслеживайте необычную активность

### Производительность

1. **Используйте PathPrefix для группировки маршрутов:**
   - Упрощает конфигурацию
   - Снижает количество правил

2. **Минимизируйте количество Gateway:**
   - Один Gateway может обслуживать множество HTTPRoute
   - Уменьшает потребление ресурсов

## Дополнительная информация

**Преимущества базового сценария:**
- **Разделение прав:** Разработчик не может случайно изменить порты или TLS шлюза.
- **Безопасность:** Кросс-неймспейс ссылки работают только при наличии `ReferenceGrant`.
- **Прозрачность:** Статус применения конфигурации виден напрямую в ресурсе (`kubectl describe httproute`).

**См. также:**
- [Определения](./definitions.md) — концепции и ролевая модель.
- [Ресурсы (CRD)](./resources.md) — глубокое описание объектов.
- [Миграция с Ingress](./migration.md) — как перенести старые правила.
- [Расширенная маршрутизация](./routing_features.md) — редиректы и разделение трафика (Canary).

**Родительская тема:** [Gateway API](./definitions.md)
