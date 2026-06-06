# Gateway API — базовые сценарии

## Определения

**Gateway API** — стандарт для управления входящим трафиком в Kubernetes, заменяющий устаревший Ingress. Основные понятия (шлюз, класс шлюза, маршрут) и ролевая модель описаны в [Определениях](./definitions.md).

**HTTPRoute** — ресурс, описывающий правила маршрутизации HTTP-запросов (хосты, пути, фильтры).

## Базовые концепции

### Цепочка взаимодействия ресурсов
Для публикации приложения в Gateway API необходимо последовательно создать три типа ресурсов, разделяющих ответственность между ролями:

1. **GatewayClass** (Инфраструктура) — выбор контроллера.
2. **Gateway** (Сеть) — открытие портов и настройка TLS.
3. **HTTPRoute** (Приложение) — описание правил маршрутизации.

Подробное описание каждого ресурса доступно в разделе [Ресурсы (CRD)](./resources.md).

## Практические сценарии

### Шаг 1: Создание класса шлюза (Администратор кластера)
Этот манифест определяет реализацию шлюзов, которая будет использоваться в кластере.

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: GatewayClass
metadata:
  name: public-lb
spec:
  controllerName: "gateway.envoyproxy.io/gatewayclass-controller"
  description: "Внешний балансировщик на базе Envoy"
```

### Шаг 2: Создание шлюза (Оператор инфраструктуры)
Шлюз резервирует порты и определяет, какие приложения могут к нему подключаться.

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: external-web
  namespace: infra
spec:
  gatewayClassName: public-lb
  listeners:
  - name: http
    protocol: HTTP
    port: 80
    allowedRoutes:
      namespaces:
        from: All # Разрешить подключение маршрутов из любых пространств имен
```

### Шаг 3: Создание правил маршрутизации (Разработчик приложения)
Разработчик описывает логику своего приложения в собственном пространстве имен.

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: my-app-route
  namespace: app-prod
spec:
  parentRefs:
  - name: external-web
    namespace: infra
  hostnames:
  - "service.example.com"
  rules:
  - matches:
    - path:
        type: PathPrefix
        value: /api
    backendRefs:
    - name: backend-service
      port: 8080
  - matches:
    - path:
        type: PathPrefix
        value: /
    backendRefs:
    - name: frontend-service
      port: 80
```

### Механизм обработки трафика
После применения манифестов происходит следующий процесс:
1. **Контроллер** (например, Envoy Gateway или Traefik) обнаруживает ресурсы и создает облачный балансировщик или настраивает MetalLB.
2. **Запрос** поступает на внешний IP-адрес шлюза.
3. **Gateway** проверяет соответствие `hostname` и передает запрос в соответствующий `HTTPRoute`.
4. **HTTPRoute** выполняет маршрутизацию на основе пути (`PathPrefix`): запросы к `/api` уходят на бэкенд, остальные — на фронтенд.

## Дополнительная информация

**Ключевые преимущества сценария:**
- **Изоляция:** ошибки в конфигурации одного приложения не влияют на работу других.
- **Гибкость:** возможность смены контроллера без изменения манифестов приложения.
- **Эффективность:** трафик может направляться напрямую на поды, минуя ClusterIP (Direct Pod Targeting).

**См. также:**
- [Определения](./definitions.md) — концепции и ролевая модель
- [Ресурсы (CRD)](./resources.md) — детальное описание параметров ресурсов
- [Миграция с Ingress](./migration.md) — пошаговое руководство по переходу
- [Расширенные функции маршрутизации](./routing_features.md) — редиректы, перезапись URL и Traffic Splitting

**Родительская тема:** [Gateway API](./definitions.md)
