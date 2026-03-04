# Horizontal Pod Autoscaler (HPA)

## Определения

**Horizontal Pod Autoscaler (HPA)** — механизм Kubernetes для автоматического изменения количества реплик подов на основе метрик загрузки.

**Metrics Server** — компонент кластера, собирающий метрики ресурсов с узлов и предоставляющий их для HPA через Metrics API (`metrics.k8s.io`).

**Stabilization Window** — период времени, в течение которого HPA учитывает исторические данные перед принятием решения о масштабировании вниз.

**Target Utilization** — целевое значение утилизации ресурса (например, 60% CPU), при котором HPA поддерживает оптимальное количество реплик.

## Основные концепции

### Алгоритм принятия решений

HPA работает по принципу термостата с периодичностью опроса 15 секунд (по умолчанию):

```
желаемыеРеплики = ceil(текущиеРеплики × (текущаяМетрика / желаемаяМетрика))
```

**Пример расчета:**
- Текущие реплики: 3
- Целевая метрика (CPU): 50%
- Текущая нагрузка: 90%
- Результат: `ceil(3 × (90 / 50)) = 6 реплик`

### Типы метрик

| Тип | Описание | Источник | Примеры |
|-----|----------|----------|---------|
| **Resource Metrics** | CPU/RAM утилизация | Metrics Server | `cpu`, `memory` |
| **Custom Metrics** | RPS, специфичные показатели | Prometheus Adapter | `http_requests_per_second`, `queue_length` |
| **External Metrics** | Длина очередей, бизнес-метрики | Внешние системы (KEDA) | `kafka_lag`, `sqs_messages` |

### Компоненты архитектуры

* **HPA Controller** — контроллер в `kube-controller-manager`, управляющий объектами HPA.
* **Metrics Server** — предоставляет ресурсные метрики через Metrics API.
* **Custom Metrics API** — адаптер (обычно Prometheus Adapter) для кастомных метрик.
* **External Metrics API** — для внешних метрик (часто через KEDA).

### Конфигурация поведения (Behavior)

Параметры `behavior` позволяют настроить скорость и агрессивность масштабирования:

| Параметр | Описание | Типичные значения |
|----------|----------|-------------------|
| `stabilizationWindowSeconds` | Задержка перед масштабированием | 0-600 секунд |
| `policies.type` | Тип политики | `Percent`, `Pods` |
| `policies.value` | Величина изменения | Процент или количество подов |
| `policies.periodSeconds` | Период применения | 15-300 секунд |
| `selectPolicy` | Выбор политики при нескольких | `Max`, `Min`, `Disabled` |

## Практические сценарии

### Предварительные требования

1. **Установить Metrics Server** — для работы с базовыми метриками (`cpu`, `memory`) в кластере должен быть развернут **Metrics Server**.

   ```bash
   kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml
   ```

   [Подробнее](../MonitoringLogging/metrics-server.md)

2. **Задать requests для контейнеров** — чтобы HPA мог корректно рассчитывать утилизацию CPU в процентах, у контейнеров должны быть установлены `requests`:

   ```yaml
   resources:
     requests:
       cpu: "200m"  # 200 милли-ядер
       memory: "256Mi"
   ```

### Сценарий 1: Базовый HPA по CPU

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: my-app-hpa
  namespace: default
spec:
  # Ссылка на масштабируемый ресурс
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: my-app

  # Границы масштабирования
  minReplicas: 3
  maxReplicas: 20

  # Метрики для принятия решений
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 60  # Целевая утилизация 60%
```

### Сценарий 2: HPA по CPU и памяти

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: multi-metric-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: my-app

  minReplicas: 3
  maxReplicas: 20

  metrics:
    # CPU метрика
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 60
    
    # Memory метрика
    - type: Resource
      resource:
        name: memory
        target:
          type: Utilization
          averageUtilization: 70
```

**Примечание:** HPA выбирает метрику, требующую наибольшего количества реплик.

### Сценарий 3: HPA с внешними метриками (очередь)

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: queue-based-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: workers

  minReplicas: 1
  maxReplicas: 50

  metrics:
    # Внешняя метрика из очереди сообщений
    - type: External
      external:
        metric:
          name: queue_messages_ready
        target:
          type: AverageValue
          averageValue: "200"  # 200 сообщений на под
```

**Примечание:** Для внешних метрик требуется Prometheus Adapter или [KEDA](keda_detailed.md).

### Сценарий 4: HPA с продвинутым поведением

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: advanced-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: web-api

  minReplicas: 5
  maxReplicas: 100

  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 70

  # Продвинутое поведение
  behavior:
    scaleUp:
      stabilizationWindowSeconds: 0  # Мгновенное масштабирование вверх
      policies:
        - type: Percent
          value: 100  # Увеличение на 100%
          periodSeconds: 15
        - type: Pods
          value: 10  # Или на 10 подов
          periodSeconds: 15
      selectPolicy: Max  # Выбрать максимальное значение
    
    scaleDown:
      stabilizationWindowSeconds: 300  # 5 минут для стабильности
      policies:
        - type: Percent
          value: 50  # Уменьшение на 50%
          periodSeconds: 60
        - type: Pods
          value: 5  # Или на 5 подов
          periodSeconds: 60
      selectPolicy: Min  # Выбрать минимальное значение
```

### Сценарий 5: HPA с кастомными метриками Prometheus

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: prometheus-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: api-server

  minReplicas: 2
  maxReplicas: 30

  metrics:
    # Кастомная метрика RPS из Prometheus
    - type: Pods
      pods:
        metric:
          name: http_requests_per_second
        target:
          type: AverageValue
          averageValue: "100"  # 100 RPS на под
```

**Примечание:** Требуется Prometheus Adapter с настроенными правилами.

### Диагностика и мониторинг

#### Проверка статуса HPA

```bash
# Список всех HPA
kubectl get hpa -A

# Детальная информация
kubectl describe hpa my-app-hpa -n default

# Текущие метрики
kubectl get --raw /apis/metrics.k8s.io/v1beta1/namespaces/default/pods

# Проверка Metrics Server
kubectl top pods -n default
kubectl top nodes
```

#### Распространённые проблемы

| Проблема | Причина | Решение |
|----------|---------|---------|
| `Waiting for metrics` | Metrics Server не работает | Проверить статус `kubectl get pods -n kube-system \| grep metrics-server` |
| `unable to get metrics` | Нет requests у контейнеров | Добавить `resources.requests` в Deployment |
| `scaling inactive` | Достигнут minReplicas/maxReplicas | Проверить границы масштабирования |
| `flapping` | Частое масштабирование | Увеличить `stabilizationWindowSeconds` |

#### Метрики для мониторинга

| Метрика | Описание |
|---------|----------|
| `kube_horizontalpodautoscaler_status_current_replicas` | Текущее количество реплик |
| `kube_horizontalpodautoscaler_status_desired_replicas` | Желаемое количество реплик |
| `kube_horizontalpodautoscaler_status_condition` | Статус условий HPA |
| `kube_horizontalpodautoscaler_spec_min_replicas` | Минимальные реплики |
| `kube_horizontalpodautoscaler_spec_max_replicas` | Максимальные реплики |

### Лучшие практики

* **Readiness Probe** — критически важна для исключения «холодных» подов из балансировки.
* **minReadySeconds** — уменьшает «флаппинг» подов, гарантирует стабильность перед включением в балансировку.
* **Корректные requests** — адекватные запросы позволяют планировщику резервировать ресурсы.
* **Behavior для scale-down** — настройте `stabilizationWindowSeconds: 300` для предотвращения частого уменьшения.
* **Выбор метрики** — для I/O-bound приложений используйте кастомные метрики (RPS), а не CPU.
* **PDB** — всегда создавайте [PodDisruptionBudget](pod_disruption_budget.md) для критических приложений.
* **Тестирование** — проверяйте масштабирование в staging перед production.

## Дополнительная информация

### Ограничения

* **Не масштабирует ниже minReplicas** — даже при нулевой нагрузке; для масштабирования до нуля используйте [KEDA](keda_detailed.md).
* **Интервал метрик** — метрики собираются с интервалом 15 секунд (настройка Metrics Server).
* **Конфликт с VPA** — не используйте HPA по CPU/memory одновременно с [VPA](vpa_detailed.md) в активных режимах (`Initial`, `Recreate`, `Auto`).
* **Только Deployment/StatefulSet/ReplicaSet** — не работает с DaemonSet, Job, CronJob.
* **Требует Metrics Server** — без Metrics Server работают только кастомные/внешние метрики.

### Интеграции

* **[Pod Disruption Budget](pod_disruption_budget.md)** — HPA учитывает PDB при масштабировании вниз.
* **[Pod Distribution](pod_distribution.md)** — созданные HPA поды распределяются согласно правилам распределения.
* **[Scaling Patterns](scaling_patterns.md)** — для масштабирования workers по длине очереди используйте внешние метрики.
* **[VPA](vpa_detailed.md)** — используйте VPA в режиме `Off` для получения рекомендаций, HPA — для горизонтального масштабирования.
* **[KEDA](keda_detailed.md)** — KEDA создаёт HPA для событийного масштабирования (очереди, расписания).
* **[Metrics Server](../MonitoringLogging/metrics-server.md)** — источник ресурсных метрик для HPA.

### Ресурсы

* [Официальная документация Kubernetes: HPA](https://kubernetes.io/docs/tasks/run-application/horizontal-pod-autoscale/)
* [Kubernetes Autoscaling SIG](https://github.com/kubernetes/autoscaler)
* [Prometheus Adapter](https://github.com/kubernetes-sigs/prometheus-adapter)
