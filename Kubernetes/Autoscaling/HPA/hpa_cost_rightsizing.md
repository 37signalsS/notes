# HPA: Cost и Right-sizing — оптимизация requests и затрат

## Определения

**Right-sizing** — процесс настройки `resources.requests` и `resources.limits` контейнеров на основе реального потребления ресурсов. Цель — найти баланс между производительностью (достаточно ресурсов) и стоимостью (нет лишних ресурсов).

**Over-provisioning** — ситуация, когда `requests` завышены относительно реального потребления. Результат: HPA не чувствителен к нагрузке (метрика не растёт), Cluster Autoscaler создает лишние узлы, растут затраты.

**Under-provisioning** — ситуация, когда `requests` занижены относительно реального потребления. Результат: HPA агрессивно масштабирует (метрика быстро растёт), поды могут быть OOMKilled или throttled, растет количество реплик.

**Cost per Request** — стоимость обработки одного запроса. Рассчитывается как: `(sum(requests × price_per_resource) × time) / total_requests`. Ключевая метрика для FinOps.

---

## Теоретический блок

### Как requests влияют на HPA

HPA рассчитывает утилизацию по формуле:

```
utilization = (current_usage / requests) × 100%
```

**Пример влияния requests на поведение HPA:**

| Сценарий | requests.cpu | Текущее потребление | Утилизация | HPA решение |
|:---|:---|:---|:---|:---|
| Завышены (over) | 1000m | 200m | 20% | Не масштабирует (цель 70%) |
| Правильно | 250m | 200m | 80% | Масштабирует |
| Занижены (under) | 100m | 200m | 200% | Агрессивно масштабирует |

### Как requests влияют на Cluster Autoscaler

CA использует `requests` для принятия решений о добавлении узлов:

```
Если (sum(requests) на всех подах) > (суммарная capacity узлов):
  → Создать новый узел
```

**Пример:**
- Узел: 4 CPU, 16Gi RAM
- Pod: requests.cpu=1000m, requests.memory=2Gi
- CA помещает на узел: 4 пода (4×1000m = 4000m ≤ 4 CPU)
- Если requests завышены (2000m на под): CA помещает только 2 пода, создает больше узлов

### Цепочка: requests → HPA → CA → Cost

```
requests.cpu = 500m (завышено, реальное потребление = 200m)
  → HPA видит 40% утилизации (цель 70%)
    → HPA не масштабирует
      → При пике: приложение тормозит, HPA не реагирует
        → ИЛИ: CA создает узлы для подов, которые потребляют только 200m
          → Paying for 500m, using 200m = 60% waste
```

### Методология right-sizing

#### Шаг 1: Сбор данных (7-14 дней)

Нужно собрать метрики потребления в разных режимах:
- Рабочие часы (пиковая нагрузка)
- Ночные часы (минимальная нагрузка)
- Выходные/праздники

#### Шаг 2: Анализ перцентилей

| Метрика | Рекомендуемый перцентиль | Почему |
|:---|:---|:---|
| CPU (requests) | P95 | HPA масштабирует по среднему, P95 покрывает 95% времени |
| CPU (limits) | P99 | Ограничение на экстремальные пики |
| Memory (requests) | P99 | Память не масштабируется, нужен запас |
| Memory (limits) | P99 + 20% | Запас под GC, spikes |

#### Шаг 3: Расчёт оптимальных requests

```
requests.cpu = P95 потребления × 1.2 (запас 20%)
requests.memory = P99 потребления × 1.3 (запас 30%)
limits.cpu = P99 потребления × 1.5 (запас 50%)
limits.memory = P99 потребления × 1.5
```

#### Шаг 4: Валидация через VPA и Goldilocks

1. Установите VPA в режиме `Off` для сбора рекомендаций
2. Дождитесь накопления данных (7+ дней)
3. Сравните рекомендации VPA с вашими расчётами
4. Если расхождение > 30% — скорректируйте requests

#### Шаг 5: Проверка влияния на HPA

```bash
# Проверка утилизации после правки requests
kubectl top pods -l app=my-app --containers

# Проверка HPA: должен масштабировать при пике
kubectl get hpa my-app-hpa -w

# PromQL: утилизация CPU vs target
# utilization = (current_usage / requests) × 100%
# HPA масштабирует, когда utilization > target (например, 70%)
```

#### Шаг 6: Проверка влияния на CA

```bash
# Проверка: CA создает узлы из-за завышенных requests?
kubectl get nodes -o custom-columns=NAME:.metadata.name,cpu-alloc:.status.allocatable.cpu,memory-alloc:.status.allocatable.memory

# Проверка: сколько подов помещается на узел?
# Поды с requests.cpu=200m на узле с 4 CPU: 4000m / 200m = 20 подов
# Поды с requests.cpu=1000m на узле с 4 CPU: 4000m / 1000m = 4 пода
```

#### Шаг 7: Итеративная оптимизация

| Параметр | Целевое значение | Как проверить |
|----------|------------------|---------------|
| CPU requests | P95 + 20% | `kubectl top pods`, VPA recommendations |
| Memory requests | P99 + 30% | `kubectl top pods`, VPA recommendations |
| HPA target utilization | 60-80% | `kubectl get hpa`, PromQL |
| CA over-provisioning | < 20% | Сравнение requests vs allocatable на узлах |

---

## Практический блок

### Инструменты для анализа

#### 1. VPA Recommender (рекомендации)

```bash
# Установка VPA в режиме Off (только рекомендации)
helm install vpa fairwinds-stable/vpa \
  --namespace monitoring \
  --set recommender.enabled=true

# Создание VPA для рекомендаций
apiVersion: autoscaling.k8s.io/v1
kind: VerticalPodAutoscaler
metadata:
  name: my-app-vpa
spec:
  targetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: my-app
  updatePolicy:
    updateMode: "Off"  # Только рекомендации, не применяются
```

**Просмотр рекомендаций:**
```bash
kubectl get vpa my-app-vpa -o yaml | grep -A 20 "recommendation"
# → containerRecommendations:
#   - containerName: app
#     lowerBound:
#       cpu: 100m
#       memory: 128Mi
#     target:
#       cpu: 250m      # Рекомендуемые requests
#       memory: 384Mi
#     upperBound:
#       cpu: 500m
#       memory: 512Mi
```

#### 2. Goldilocks (визуализация рекомендаций)

```bash
# Установка Goldilocks
helm install goldilocks fairwinds-stable/goldilocks \
  --namespace monitoring

# Просмотр рекомендаций
kubectl port-forward -n monitoring svc/goldilocks 8080:80
# Открыть http://localhost:8080
```

#### 3. Kubecost (анализ затрат)

```bash
# Установка Kubecost
helm install kubecost cost-analyzer \
  --namespace kubecost \
  --set kubecostToken="YOUR_TOKEN"

# Просмотр cost allocation
kubectl port-forward -n kubecost svc/cost-analyzer 9090:9090
```

### PromQL для анализа right-sizing

**1. Фактическое потребление vs requests:**
```promql
# CPU: фактическое потребление vs requests (в процентах)
sum(rate(container_cpu_usage_seconds_total{
  namespace="$namespace", pod=~"$pod.*"
}[5m])) by (pod)
/
sum(kube_pod_container_resource_requests{
  namespace="$namespace", pod=~"$pod.*", resource="cpu"
}) by (pod) * 100
```

**2. Over-provisioning (requests >> usage):**
```promql
# Поды, где requests > 2× фактического потребления
(
  kube_pod_container_resource_requests{resource="cpu"}
  - sum(rate(container_cpu_usage_seconds_total[5m])) by (pod, namespace)
) / kube_pod_container_resource_requests{resource="cpu"} * 100 > 50
```

**3. Under-provisioning (usage >> requests):**
```promql
# Поды, где потребление > 80% requests (риск OOM/throttle)
sum(rate(container_cpu_usage_seconds_total[5m])) by (pod, namespace)
/ kube_pod_container_resource_requests{resource="cpu"} * 100 > 80
```

**4. Стоимость HPA:**
```promql
# Примерная стоимость CPU (в условных единицах)
sum(
  kube_pod_container_resource_requests{resource="cpu"}
  * on(pod, namespace) group_left()
  kube_pod_info
) * $cpu_price_per_core
```

### Сценарий: Оптимизация HPA после right-sizing

**До оптимизации:**
```yaml
# Завышенные requests
resources:
  requests:
    cpu: "1000m"    # Реальное потребление: 200m
    memory: "1Gi"   # Реальное потребление: 256Mi
# HPA: averageUtilization: 70%
# Результат: HPA не масштабирует (utilization = 20%)
# Cluster Autoscaler создает узлы для "phantom" ресурсов
```

**После оптимизации:**
```yaml
# Правильные requests (на основе P95 + запас)
resources:
  requests:
    cpu: "250m"     # P95 = 200m × 1.2
    memory: "384Mi" # P99 = 300Mi × 1.3
  limits:
    cpu: "500m"     # P99 = 350m × 1.5
    memory: "512Mi"
# HPA: averageUtilization: 70%
# Результат: HPA масштабирует при реальной нагрузке
# Cluster Autoscaler создает только необходимые узлы
```

**Эффект:**
| Метрика | До | После | Экономия |
|:---|:---|:---|:---|
| requests.cpu на под | 1000m | 250m | 75% |
| Реплики при нагрузке | 3 (HPA не реагировал) | 8 (HPA масштабировал) | Более точное |
| Узлов CA | 6 | 3 | 50% |
| Стоимость CPU | $600/мес | $200/мес | 66% |

### Мониторинг cost метрик

```yaml
# Алерт: HPA не масштабирует из-за завышенных requests
groups:
  - name: rightsizing
    rules:
      - alert: OverProvisionedCPU
        expr: |
          (
            kube_pod_container_resource_requests{resource="cpu"}
            - sum(rate(container_cpu_usage_seconds_total[5m])) by (pod, namespace)
          ) / kube_pod_container_resource_requests{resource="cpu"} * 100 > 70
        for: 1h
        labels:
          severity: info
        annotations:
          summary: "Завышенные CPU requests: {{ $labels.pod }}"
          description: "Requests превышают потребление на {{ $value }}%. Рекомендуется right-sizing."

      - alert: HPAStuckAtMin
        expr: |
          kube_horizontalpodautoscaler_status_current_replicas
          == kube_horizontalpodautoscaler_spec_min_replicas
          and
          kube_horizontalpodautoscaler_status_condition{
            condition="ScalingLimited",status="false"
          } == 1
        for: 2h
        labels:
          severity: info
        annotations:
          summary: "HPA {{ $labels.horizontalpodautoscaler }} не масштабируется"
          description: "HPA на minReplicas > 2 часа. Возможно, requests завышены."
```

---

## Дополнительная информация

### Чек-лист right-sizing

1. [ ] Собраны метрики за 7-14 дней (VPA Recommender или Prometheus)
2. [ ] Определены P95/P99 для CPU и Memory
3. [ ] requests установлены = P95 × 1.2 (CPU), P99 × 1.3 (Memory)
4. [ ] limits установлены = P99 × 1.5
5. [ ] HPA averageUtilization настроен (обычно 60-70%)
6. [ ] Протестировано в staging перед применением в production
7. [ ] Настроен мониторинг (over/under-provisioning alerts)
8. [ ] Периодический пересмотр (ежемесячно или при изменении нагрузки)

### Типичные ошибки

| Ошибка | Последствие | Решение |
|:---|:---|:---|
| requests = limits (Burstable) | OOMKilled при spike | requests < limits |
| requests = фактическому usage | Нет запаса, HPA не успевает | requests = usage × 1.2 |
| requests завышены в 5× | HPA не масштабирует, CA раздувает кластер | Right-sizing по P95 |
| limits не заданы | Unbounded, конкурентная борьба за CPU | Всегда задавать limits |
| Нет разницы между env | Dev=prod requests, перерасход | Разные requests для different environments |

### Советы для собеседования

**Вопрос:** Как оптимизировать requests для HPA?
**Ответ:** Метод из 3 шагов:
1. **Сбор:** VPA Recommender в режиме Off собирает P95/P99 потребления за 8-14 дней
2. **Расчёт:** requests = P95 × 1.2 (CPU), P99 × 1.3 (Memory)
3. **Валидация:** Тестирование в staging, мониторинг over/under-provisioning через Prometheus

Ключевой инсайт: завышенные requests = HPA не чувствителен к нагрузке + CA создает лишние узлы = переплата 50-70%.

---

### См. также

- **[HPA: Продвинутые темы](./hpa_advanced.md)** — взаимодействие с ResourceQuota и VPA
- **[KEDA: FinOps](../keda/keda-finops.md)** — финансовая сторона масштабирования
- **[VPA](../vpa_detailed.md)** — рекомендации по requests
- **[Cluster Autoscaler](../cluster_autoscaler_detailed.md)** — инфраструктурное масштабирование
- **[Kubecost](../../MonitoringLogging/kubecost.md)** — анализ затрат
- **[Goldilocks](../../ToolsUtilities/goldilocks.md)** — визуализация рекомендаций
