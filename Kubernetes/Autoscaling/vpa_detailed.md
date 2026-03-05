# Vertical Pod Autoscaler (VPA)

## Определения

**Vertical Pod Autoscaler (VPA)** — механизм Kubernetes для автоматического изменения ресурсов (`requests` и `limits` CPU/memory) у контейнеров в подах на основе истории потребления.

**Overprovisioning** — ситуация, когда запрошено значительно больше ресурсов, чем реально используется (ведёт к неэффективному использованию кластера).

**Underprovisioning** — ситуация, когда запрошено недостаточно ресурсов, приводящая к `OOMKilled` или снижению производительности.

**Recommendation** — рекомендация VPA по оптимальным значениям `requests` и `limits` на основе исторических данных.

## Основные концепции

### Компоненты VPA

| Компонент | Назначение |
|-----------|------------|
| **VPA Recommender** | Следит за историей потребления ресурсов и рассчитывает оптимальные значения `requests`/`limits` |
| **VPA Updater** | Отвечает за применение рекомендаций, выселяя (`evict`) поды для обновления ресурсов |
| **VPA Admission Controller** | Вебхук, перехватывающий запросы на создание подов и подменяющий `requests` на рекомендованные |

### Режимы работы (`updateMode`)

| Режим | Описание | Когда использовать |
|-------|----------|-------------------|
| **`Off`** | VPA только анализирует потребление и записывает рекомендации, не применяя их | Начальный этап, сбор данных, критические сервисы |
| **`Initial`** | VPA применяет рекомендации только в момент создания пода. Уже работающие поды не затрагиваются | Постепенное внедрение, stateful-приложения |
| **`Recreate`** | VPA применяет рекомендации как при создании, так и для уже работающих подов, **перезапуская** их при необходимости | Ночные окна обслуживания, fault-tolerant приложения |
| **`Auto`** | Аналогично `Recreate`, но с Kubernetes 1.35+ может применять изменения без перезапуска через [In-Place Pod Resize](in_place_pod_resize.md) | Production с Kubernetes 1.35+ |

### Принцип работы

1. **Сбор данных** — VPA собирает метрики потребления ресурсов через Metrics API.
2. **Анализ** — Recommender анализирует исторические данные (обычно за 24 часа).
3. **Расчёт рекомендаций** — вычисляются оптимальные значения на основе percentiles (95-й для CPU, 99-й для memory).
4. **Применение** — в активных режимах Updater создаёт Eviction для подов, Admission Controller подменяет ресурсы при создании.

### Формула расчёта рекомендаций

* **CPU request** — 95-й перцентиль потребления за последние 24 часа
* **CPU limit** — 115% от recommended request
* **Memory request** — 99-й перцентиль потребления за последние 24 часа
* **Memory limit** — 115% от recommended request (или фиксированный коэффициент)

## Практические сценарии

### Установка VPA

```bash
# Клонируем репозиторий
git clone https://github.com/kubernetes/autoscaler.git
cd autoscaler/vertical-pod-autoscaler

# Устанавливаем VPA
./hack/vpa-up.sh

# Проверка установки
kubectl get pods -n kube-system | grep vpa
```

### Сценарий 1: Базовая конфигурация (режим Off)

```yaml
apiVersion: autoscaling.k8s.io/v1
kind: VerticalPodAutoscaler
metadata:
  name: my-app-vpa
  namespace: default
spec:
  # Целевой ресурс
  targetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: my-app
  
  # Режим только рекомендаций
  updatePolicy:
    updateMode: "Off"
  
  # Политика ресурсов
  resourcePolicy:
    containerPolicies:
      - containerName: '*'
        minAllowed:
          cpu: 100m
          memory: 50Mi
        maxAllowed:
          cpu: "2"
          memory: "4Gi"
        controlledResources:
          - cpu
          - memory
```

### Сценарий 2: VPA с режимом Initial

```yaml
apiVersion: autoscaling.k8s.io/v1
kind: VerticalPodAutoscaler
metadata:
  name: stateful-vpa
spec:
  targetRef:
    apiVersion: apps/v1
    kind: StatefulSet
    name: database
  
  updatePolicy:
    updateMode: "Initial"  # Применяется только к новым подам
  
  resourcePolicy:
    containerPolicies:
      - containerName: database
        minAllowed:
          cpu: "500m"
          memory: "1Gi"
        maxAllowed:
          cpu: "4"
          memory: "16Gi"
```

### Сценарий 3: VPA с режимом Recreate (для ночного обслуживания)

```yaml
apiVersion: autoscaling.k8s.io/v1
kind: VerticalPodAutoscaler
metadata:
  name: batch-processor-vpa
spec:
  targetRef:
    apiVersion: batch/v1
    kind: Job
    name: nightly-batch
  
  updatePolicy:
    updateMode: "Recreate"  # Перезапускает поды для применения
  
  resourcePolicy:
    containerPolicies:
      - containerName: processor
        controlledValues: RequestsOnly  # Управляет только requests
        minAllowed:
          cpu: "1"
          memory: "2Gi"
```

### Сценарий 4: VPA с режимом Auto (Kubernetes 1.35+)

```yaml
apiVersion: autoscaling.k8s.io/v1
kind: VerticalPodAutoscaler
metadata:
  name: web-api-vpa
spec:
  targetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: web-api
  
  updatePolicy:
    updateMode: "Auto"  # Использует In-Place Pod Resize
  
  resourcePolicy:
    containerPolicies:
      - containerName: api
        minAllowed:
          cpu: 200m
          memory: 256Mi
        maxAllowed:
          cpu: "1"
          memory: "2Gi"
        controlledResources:
          - cpu
          - memory
        # Фиксированное соотношение request/limit
        maxAllowedRequestToBaseRatio: 1.2
```

### Диагностика и мониторинг

#### Проверка рекомендаций VPA

```bash
# Список всех VPA
kubectl get vpa -A

# Детальная информация с рекомендациями
kubectl describe vpa my-app-vpa -n default

# Проверка статуса рекомендаций
kubectl get vpa my-app-vpa -o jsonpath='{.status.recommendation.containerRecommendations}'
```

#### Пример вывода рекомендаций

```yaml
containerRecommendations:
  - containerName: app
    lowerBound:
      cpu: 150m
      memory: 200Mi
    target:
      cpu: 250m
      memory: 350Mi
    uncappedTarget:
      cpu: 300m
      memory: 400Mi
    upperBound:
      cpu: 400m
      memory: 500Mi
```

| Поле | Описание |
|------|----------|
| `lowerBound` | Минимальные безопасные значения |
| `target` | Рекомендуемые значения (оптимальные) |
| `uncappedTarget` | Рекомендации без учёта `maxAllowed` |
| `upperBound` | Максимальные значения перед overprovisioning |

#### Метрики для мониторинга

| Метрика | Описание |
|---------|----------|
| `vpa_recommender_cpu_recommendation` | Рекомендации по CPU |
| `vpa_recommender_memory_recommendation` | Рекомендации по памяти |
| `vpa_updater_evictions_total` | Количество eviction'ов |
| `vpa_admission_controller_requests_total` | Запросы к Admission Controller |

### Лучшие практики

* **Начните с режима `Off`** — соберите рекомендации 1-2 недели без риска.
* **Анализируйте рекомендации** — проверьте соответствие ожиданиям и лимитам.
* **Переходите к `Initial`** — применяйте изменения постепенно к новым подам.
* **Используйте `Auto` с Kubernetes 1.35+** — для применения без перезапуска.
* **Настройте `minAllowed`/`maxAllowed`** — предотвратите недопустимые значения.
* **PDB для критичных сервисов** — [PodDisruptionBudget](pod_disruption_budget.md) минимизирует прерывания.
* **Избегайте частых изменений** — VPA требует времени для стабилизации рекомендаций.

## Дополнительная информация

### Совместное использование с HPA

**Конфликт:** Не используйте VPA в режимах `Initial`, `Recreate` или `Auto` для CPU/memory одновременно с HPA по тем же метрикам.

**Причина:** HPA пытается увеличить количество подов при высокой утилизации, а VPA в это же время увеличивает `requests`, что приводит к:

* Постоянным перезапускам подов
* «Гонке масштабирования»
* Нестабильности приложения

**Решения:**

| Подход | Описание |
|--------|----------|
| **VPA `Off` + HPA** | VPA даёт рекомендации, HPA масштабирует горизонтально. Ручная настройка `requests` по рекомендациям. |
| **VPA для CPU + HPA для memory** | Разделение метрик между компонентами. |
| **VPA `Auto` (K8s 1.35+) + HPA** | VPA использует In-Place Resize, HPA масштабирует по кастомным метрикам (RPS). |

### Ограничения

* **Требуется перезапуск** — до Kubernetes 1.35 VPA требовал перезапуска подов для применения изменений.
* **Конфликт с HPA** — не используйте для одних и тех же метрик одновременно.
* **Время обучения** — требуется 24+ часа для сбора статистики и точных рекомендаций.
* **Не работает с DaemonSet** — VPA не поддерживает DaemonSet, Job, CronJob.
* **Требует Admission Controller** — для автоматического применения нужен вебхук.

### Интеграции

* **[In-Place Pod Resize](in_place_pod_resize.md)** — VPA в режиме `Auto` использует для применения без перезапуска (Kubernetes 1.35+).
* **[HPA](hpa_detailed.md)** — используйте VPA в режиме `Off` для рекомендаций, HPA — для горизонтального масштабирования.
* **[Pod Disruption Budget](pod_disruption_budget.md)** — PDB минимизирует прерывания при eviction подов VPA.
* **[Scaling Patterns](scaling_patterns.md)** — VPA помогает оптимизировать ресурсы для различных паттернов.

### Ресурсы

* [Официальная документация Kubernetes: VPA](https://github.com/kubernetes/autoscaler/tree/master/vertical-pod-autoscaler)
* [GitHub репозиторий VPA](https://github.com/kubernetes/autoscaler/tree/master/vertical-pod-autoscaler)
* [Kubernetes 1.35: In-Place Pod Resize GA](https://kubernetes.io/blog/2024/12/kubernetes-v1-35-in-place-pod-resize-ga/)
