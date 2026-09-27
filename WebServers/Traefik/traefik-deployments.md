# Развертывание Traefik: Blue/Green, Canary, Rolling Update

## Определения

**Blue/Green deployment** — стратегия развертывания с двумя идентичными средами (Blue и Green). Трафик переключается атомарно с Blue на Green.

**Canary deployment** — постепенное переключение трафика на новую версию: сначала 1%, затем 5%, 25%, 100%.

**Traffic splitting** — распределение трафика между версиями по весам без изменения количества реплик.

**Rolling update** — последовательное обновление реплик, при котором в каждый момент часть реплик работает со старой, часть с новой версией.

**Service mesh migration** — переход трафика между сервисами через внешний механизм (Service Mesh, Ingress Controller, Gateway API).

## Базовые концепции

### Почему Traefik для progressive delivery

Traefik поддерживает несколько механизмов управления трафиком:
- **Weighted Round Robin** между сервисами (canary, blue/green).
- **Mirroring** для тестирования на реальном трафике.
- **Failover** для автоматического переключения на резервный сервис.
- **Multi-layer routing** для сложных правил маршрутизации.
- Внешний LB (MetalLB, cloud LB) для переключения на уровне L4.

### Blue/Green через Traefik

Два подхода:
1. **Переключение weights**: два сервиса (blue, green), Traefik направляет 100% на один, затем переключает на другой.
2. **Переключение на уровне Gateway/LB**: Traefik остается тем же, меняется адрес бэкенда.

### Canary через Traefik

В weighted services Traefik поддерживает проценты на уровне сервисов. Для API gateway подходит Gradual traffic shifting.

### Rolling Update с Traefik

Traefik OSS stateless: можно обновлять реплики по одной. Внешний LB должен иметь health check `/ping` для корректного drain.

### Интеграция с Argo Rollouts / Flagger

Для автоматизации progressive delivery используют:
- **Flagger**: управляет weights через IngressRoute/Middleware или Gateway API.
- **Argo Rollouts**: управляет Deployment + Service или Ingress.

## Практические сценарии

### Сценарий 1: Blue/Green через weighted services

```yaml
# services:
http:
  services:
    app-blue:
      loadBalancer:
        servers:
        - url: http://app-blue:8080
    app-green:
      loadBalancer:
        servers:
        - url: http://app-green:8080
    app:
      weighted:
        services:
        - name: app-blue
          weight: 100  # 100% на blue
        - name: app-green
          weight: 0    # 0% на green
  routers:
    app:
      rule: Host(`app.example.com`)
      service: app
      entryPoints: [websecure]
      middlewares:
      - redirect-https
```

Переключение на green:
```yaml
# Измените weights:
    app:
      weighted:
        services:
        - name: app-blue
          weight: 0
        - name: app-green
          weight: 100
```

### Сценарий 2: Canary deployment (постепенный рост)

```yaml
http:
  services:
    app-v1:
      loadBalancer:
        servers:
        - url: http://app-v1:8080
    app-v2:
      loadBalancer:
        servers:
        - url: http://app-v2:8080
    app:
      weighted:
        services:
        - name: app-v1
          weight: 95
        - name: app-v2
          weight: 5
```

Постепенный рост canary:
1. `weight: 5` → наблюдение метрик 5-10 минут
2. `weight: 25` → наблюдение
3. `weight: 50` → наблюдение
4. `weight: 100` → полный переход

### Сценарий 3: Blue/Green через переключение Service selector

```yaml
# Blue Service (активный)
apiVersion: v1
kind: Service
metadata:
  name: app
  namespace: prod
spec:
  selector:
    app: app
    version: blue
  ports:
  - port: 80
    targetPort: 8080
---
# Green Service (резервный)
apiVersion: v1
kind: Service
metadata:
  name: app-green
  namespace: prod
spec:
  selector:
    app: app
    version: green
  ports:
  - port: 80
    targetPort: 8080
---
# Traefik направляет на app (blue)
http:
  services:
    app:
      loadBalancer:
        servers:
        - url: http://app.prod.svc.cluster.local:80
```

Переключение: измените selector в Service `app` на `version: green`.

### Сценарий 4: Canary с Flagger

```yaml
apiVersion: flagger.app/v1beta1
kind: Canary
metadata:
  name: app
  namespace: prod
spec:
  targetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: app
  progressDeadlineSeconds: 60
  service:
    port: 80
    targetPort: 8080
  analysis:
    interval: 1m
    threshold: 5
    maxWeight: 50
    stepWeight: 10
    metrics:
    - name: request-success-rate
      thresholdRange:
        min: 99
      interval: 1m
```

Flagger автоматически управляет weights через IngressRoute/Middleware.

### Сценарий 5: Rolling Update с внешним LB

```yaml
# Service Traefik
apiVersion: v1
kind: Service
metadata:
  name: traefik
  namespace: traefik
spec:
  type: LoadBalancer
  selector:
    app.kubernetes.io/name: traefik
  ports:
  - name: web
    port: 80
    targetPort: 80
  - name: websecure
    port: 443
    targetPort: 443
```

Внешний LB (MetalLB, cloud LB) шлет health check на `/ping`. При drain ноды:
1. LB перестает отправлять трафик на ноду (503 на /ping).
2. Traefik завершает активные соединения (`graceTimeout`).
3. Pod удаляется.
4. Следующий pod обновляется.

### Сценарий 6: A/B testing через Header-based routing

```yaml
http:
  routers:
    app-a:
      rule: Host(`app.example.com`) && Header(`X-Version`, `a`)
      service: app-v1
      entryPoints: [websecure]
      priority: 100
    app-b:
      rule: Host(`app.example.com`) && Header(`X-Version`, `b`)
      service: app-v2
      entryPoints: [websecure]
      priority: 100
    app-default:
      rule: Host(`app.example.com`)
      service: app-v1
      entryPoints: [websecure]
      priority: 1
```

### Сценарий 7: Shadow deployment (трафик дублируется)

```yaml
http:
  services:
    app-primary:
      loadBalancer:
        servers:
        - url: http://app-primary:8080
    app-shadow:
      loadBalancer:
        mirroring:
          service: app-primary
          mirrors:
          - name: app-new
            percent: 10
```

## Операции и команды

```bash
# Проверка текущих weights
kubectl get ingressroute app -n prod -o yaml | grep -A 5 "weighted"

# Применение новых weights
kubectl apply -f ingressroute-canary.yaml

# Проверка метрик во время canary
kubectl port-forward -n traefik svc/traefik 9100:9100
curl -s localhost:9100/metrics | grep 'traefik_service_requests_total'

# Проверка health check
curl -s http://traefik:8080/ping
# → OK
```

## Устранение неисправлений

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Canary не переключает трафик** | Weights не изменились, кэш | Проверьте IngressRoute, примените изменения |
| **Traffic split не работает** | Priority роутеров конфликтует | Задайте явные priority для всех роутеров |
| **Pod drain зависает** | `graceTimeout` слишком мал, бэкенд не отвечает | Увеличьте `graceTimeout`, настройте health check |
| **LB дергает ноды** | `/ping` отвечает 503 при drain | Настройте passive health check на LB |
| **A/B не работает** | Header не передается клиентом | Проверьте заголовок на стороне клиента |

## Рекомендации

- Для canary используйте weighted services + внешний мониторинг метрик.
- Для blue/green используйте Service selector switching при интеграции с K8s Deployment.
- Всегда оставляйте `priority` явно для перекрывающихся правил.
- При rolling update Traefik используйте external LB с health check `/ping`.
- Для автоматизации используйте Flagger или Argo Rollouts.
- Не делайте canary слишком маленьким (< 5%) — метрики будут нестабильны.

## Дополнительная информация

- [Обзор Traefik](./traefik_overview.md) — weighted services, canary, mirroring.
- [Middleware для управления трафиком](./traefik-middlewares-traffic.md) — RateLimit, CircuitBreaker для защиты canary.
- [Traefik в Kubernetes](./traefik-kubernetes.md) — CRD, RBAC, Helm.
- [Gateway API Traefik](../../Kubernetes/Networking/gateway_api/traefik.md) — HTTPRoute weights.
- [Progressive Delivery в GitOps](../../GitOps/Concepts/progressive_delivery_gitops.md) — Flagger, Argo Rollouts.
- [Blue-Green Deployment](../../../CI-CD/Deployment_Strategies/blue_green_deployment.md) — общая теория.
- [Canary Deployment](../../../CI-CD/Deployment_Strategies/canary_deployment.md) — общая теория.
