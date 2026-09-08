# Каскадное масштабирование микросервисов (Cascading Scaling)

## Определения

**Каскадное масштабирование (Cascading Scaling)** — ситуация, при которой автоматическое масштабирование одного сервиса генерирует нагрузку на зависимые сервисы, вызывая их масштабирование. Процесс может распространяться по всей цепочке зависимостей.

**Bottleneck (узкое место)** — компонент системы, пропускная способность которого ограничивает общую производительность. При каскадном масштабировании bottleneck — это сервис, который не масштабируется или масштабируется медленнее, чем генерирует нагрузку.

**Trickle-down Scaling Lag** — задержка между моментом масштабирования upstream-сервиса и моментом, когда downstream-сервис обрабатывает увеличенную нагрузку. Складывается из: времени масштабирования HPA + времени создания пода + времени прохождения readiness probe.

**Capacity Headroom** — запас ресурсов, необходимый для обработки пиковых нагрузок при каскадном масштабировании. Определяется как разность между `maxReplicas * requests` и реальным потреблением.

---

## Теоретический блок

### Архитектура типичной цепочки

```
                         ┌─────────────┐
                         │   Ingress    │
                         │  Controller │
                         └──────┬──────┘
                                │
                    ┌───────────▼───────────┐
                    │     Frontend (HPA)     │
                    │  CPU: 70%, RPS-based   │
                    └───────────┬───────────┘
                                │
              ┌─────────────────┼─────────────────┐
              │                 │                 │
    ┌─────────▼─────────┐ ┌────▼──────────┐ ┌────▼──────────┐
    │   API Gateway     │ │   Auth Service│ │  Rate Limiter │
    │     (HPA)         │ │    (HPA)      │ │    (HPA)      │
    └─────────┬─────────┘ └───────────────┘ └───────────────┘
              │
    ┌─────────▼─────────┐
    │  Backend Service  │
    │      (HPA)        │
    └─────────┬─────────┘
              │
    ┌─────────▼─────────┐
    │    Database        │
    │  (StatefulSet)     │
    └───────────────────┘
```

### Типы каскадных проблем

#### 1. Прямой каскад (Direct Cascade)
Frontend масштабируется → увеличивает нагрузку на Backend → Backend масштабируется → нагружает Database.

**Проблема:** Database не имеет HPA (StatefulSet), и при определённом количестве реплик Backend упирается в пропускную способность БД.

#### 2. Обратный каскад (Reverse Cascade)
Backend масштабируется → начинает больше читать из Database → Database уходит в high CPU → Frontend получает timeouts → HPA Frontend масштабирует → ещё больше нагрузки на Backend.

**Проблема:** Само масштабирование усугубляет проблему (piętrowy efekt).

#### 3. Параллельный каскад (Parallel Cascade)
Несколько сервисов масштабируются одновременно и конкурируют за общий ресурс (CPU, память, сеть, Disk I/O).

**Проблема:** Ни один сервис не достигает целевых метрик, все HPA на максимуме.

### Математическая модель

Если upstream-сервис масштабируется с `N` до `M` реплик, а каждый под генерирует `R` RPS к downstream:

```
Нагрузка на downstream = M × R
```

Downstream должен иметь:
```
maxReplicas ≥ ceil(M × R / target_RPS_per_pod)
```

**Пример:**
- Frontend: min=3, max=20, каждый под генерирует 200 RPS к Backend
- Backend: min=3, max=15, target=500 RPS на под
- При масштабировании Frontend до 20: Backend получает 20 × 200 = 4000 RPS
- Backend нужен: ceil(4000 / 500) = 8 реплик (в пределах max=15 ✓)

Но если Backend-Database не может обработать больше 5000 RPS:
- Максимум Backend реплик: ceil(5000 / 500) = 10
- Максимум Frontend реплик: ceil(10 × 500 / 200) = 25, но Database упрётся

### Стратегии защиты от каскадного масштабирования

| Стратегия | Описание | Когда использовать |
|:---|:---|:---|
| **Independent HPA** | Каждый сервис имеет собственный HPA с независимыми метриками | Базовый подход, microservices |
| **Rate Limiting** | Ограничение входящей нагрузки на каждом уровне | Защита от cascading failure |
| **Circuit Breaker** | Блокировка запросов при превышении порога ошибок | Защита downstream сервисов |
| **Load Shedding** | Отбрасывание запросов при перегрузке | Критические сервисы |
| **Bulkhead Pattern** | Изоляция ресурсов для разных потребителей | Multi-tenant системы |
| **Backpressure** | Передача информации о перегрузке upstream | Очереди сообщений |

---

## Практический блок

### Паттерн 1: Независимые HPA с разными метриками

Каждый сервис масштабируется по своей метрике, а не по нагрузке от upstream:

```yaml
# Frontend — масштабируется по RPS (своя метрика)
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: frontend-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: frontend
  minReplicas: 3
  maxReplicas: 20
  metrics:
    - type: Pods
      pods:
        metric:
          name: http_requests_per_second
        target:
          type: AverageValue
          averageValue: "1000"
---
# Backend — масштабируется по CPU (не зависит от Frontend)
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: backend-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: backend
  minReplicas: 3
  maxReplicas: 15
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 65
  behavior:
    scaleUp:
      stabilizationWindowSeconds: 0
      policies:
        - type: Percent
          value: 50
          periodSeconds: 30
    scaleDown:
      stabilizationWindowSeconds: 300
      policies:
        - type: Pods
          value: 1
          periodSeconds: 60
```

**Преимущества:** Каждый сервис реагирует на свою нагрузку, нет прямой связи.
**Недостатки:** Backend может не успеть за Frontend при резком пике.

### Паттерн 2: Rate Limiting на каждом уровне

```yaml
# Nginx Ingress — Limit Req (ограничение RPS на под)
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: frontend-ingress
  annotations:
    nginx.ingress.kubernetes.io/limit-rps: "100"
    nginx.ingress.kubernetes.io/limit-burst-multiplier: "5"
    nginx.ingress.kubernetes.io/proxy-connect-timeout: "10"
    nginx.ingress.kubernetes.io/proxy-read-timeout: "30"
spec:
  rules:
    - host: app.example.com
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: frontend
                port:
                  number: 80
```

**Результат:** Ingress отдаёт 429 Too Many Requests при превышении лимита, защищая Backend от перегрузки.

### Паттерн 3: Circuit Breaker через Envoy/Istio

```yaml
apiVersion: networking.istio.io/v1beta1
kind: DestinationRule
metadata:
  name: backend-circuit-breaker
spec:
  host: backend
  trafficPolicy:
    connectionPool:
      tcp:
        maxConnections: 100
      http:
        h2UpgradePolicy: DEFAULT
        http1MaxPendingRequests: 100
        http2MaxRequests: 1000
        maxRequestsPerConnection: 10
        maxRetries: 3
    outlierDetection:
      consecutive5xxErrors: 5
      interval: 30s
      baseEjectionTime: 30s
      maxEjectionPercent: 50
```

**Результат:** При 5xx-ошибках > 5 за 30 секунд, проблемные поды временно исключаются из балансировки.

### Паттерн 4: Проверка цепочки перед масштабированием

```bash
# Чек-лист перед включением HPA на production:

# 1. Проверить, что downstream сервисы имеют достаточный maxReplicas
kubectl get hpa -A | grep -E "NAME|backend|database"

# 2. Проверить ResourceQuota в namespace downstream
kubectl get resourcequota -n backend-ns

# 3. Проверить, что Database выдержит нагрузку
kubectl top pods -l app=database --sort-by=cpu

# 4. Проверить PDB на каждом уровне
kubectl get pdb -A

# 5. Протестировать под нагрузкой
kubectl run load-test --rm -i --tty --image=fortio -- \
  load -c 10 -qps 100 -t 60s http://frontend:8080/api
```

### Паттерн 5: Мониторинг каскадного масштабирования

```yaml
# Алерт: Backend на maxReplicaswhile Frontend ainda не на максимуме
groups:
  - name: cascading_scaling
    rules:
      - alert: CascadingScalingDetected
        expr: |
          kube_horizontalpodautoscaler_status_condition{
            condition="ScalingLimited",status="true"
          } == 1
          and
          kube_horizontalpodautoscaler_status_current_replicas
          / kube_horizontalpodautoscaler_spec_max_replicas > 0.8
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Возможно каскадное масштабирование: {{ $labels.horizontalpodautoscaler }}"
          description: "HPA на maxReplicas >80%. Проверьте downstream-сервисы."

      - alert: DownstreamLatencyHigh
        expr: |
          histogram_quantile(0.99,
            rate(http_request_duration_seconds_bucket{
              service="backend"
            }[5m])
          ) > 1
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Backend latency p99 > 1s"
          description: "Backend не справляется с нагрузкой. Проверьте Database и масштабирование."
```

---

## Дополнительная информация

### Антипаттерны

| Антипаттерн | Последствие | Решение |
|:---|:---|:---|
| HPA на Frontend без лимита на Backend | Backend перегружается, падает | Rate Limiting + independent HPA |
| Все сервисы масштабируются по CPU | Database bottleneck | Кастомные метрики для каждого уровня |
| Нет Circuit Breaker | Каскадный отказ | Circuit breaker на каждом уровне |
| Один HPA на несколько сервисов | Непредсказуемое поведение | Один HPA = один сервис |
| minReplicas > maxReplicas downstream | HPA застревает | Проверять maxReplicas цепочки |

### Чек-лист для production

1. [ ] Каждый сервис имеет собственный HPA
2. [ ] HPA настроен с `behavior` (scaleUp агрессивный, scaleDown консервативный)
3. [ ] Rate Limiting на Ingress-уровне
4. [ ] Circuit Breaker между сервисами (Istio/Envoy)
5. [ ] PDB на каждом сервисе
6. [ ] Мониторинг latency на каждом уровне
7. [ ] Алерты на каскадное масштабирование
8. [ ] Тестирование под нагрузкой перед включением HPA
9. [ ] ResourceQuota в namespace критичных сервисов
10. [ ] Documentation цепочки зависимостей

### Советы для собеседования

**Вопрос:** Как предотвратить каскадное масштабирование в микросервисах?
**Ответ:** Три уровня защиты:
1. **Independent HPA:** Каждый сервис масштабируется по своей метрике (RPS для Frontend, CPU для Backend, latency для API Gateway), а не по нагрузке от upstream.
2. **Rate Limiting + Circuit Breaker:** Ingress ограничивает RPS, Circuit Breaker блокирует запросы при превышении порога ошибок.
3. **Capacity Planning:** Проверять, что maxReplicas downstream выдерживает maxReplicas upstream × RPS_per_pod.

---

### См. также

- **[HPA: Практические сценарии](./hpa_scenarios.md)** — YAML-манифесты для каждого типа метрик
- **[HPA: Продвинутые темы](./hpa_advanced.md)** — настройка behavior для каждого сервиса
- **[Pod Disruption Budget](../pod_disruption_budget.md)** — защита доступности при масштабировании
- **[Cluster Autoscaler](../cluster_autoscaler_detailed.md)** — инфраструктурное масштабирование
