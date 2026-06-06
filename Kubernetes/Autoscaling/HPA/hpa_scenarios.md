# Horizontal Pod Autoscaler (HPA): Практические сценарии

В данном документе представлены типовые конфигурации горизонтального масштабирования подов (Horizontal Pod Autoscaler, HPA) для различных типов нагрузки в Kubernetes.

## Определения

Для получения базовой информации см. основной раздел **[HPA (index.md)](./index.md)**.

**HPA v2 API** — текущая версия интерфейса программирования приложений (Application Programming Interface, API), поддерживающая кастомные и внешние метрики, а также настройку поведения.

**Metrics-driven Scaling** — подход к масштабированию, при котором количество реплик определяется внешними или внутренними показателями производительности, а не только потреблением ресурсов.

## Базовые концепции

### Предварительные требования

Для успешного применения любого из сценариев ниже необходимо выполнение двух условий:

1. **Metrics Server:** должен быть развернут в кластере для сбора данных о потреблении ресурсов (ЦПУ/Память).
   [Инструкция по установке в разделе Metrics Server](../../MonitoringLogging/metrics-server.md)

2. **Resource Requests:** HPA использует запросы ресурсов (`requests`) в качестве базовой линии для расчета процента утилизации. Без них расчет в процентах невозможен.

   ```yaml
   resources:
     requests:
       cpu: "200m"  # Центральный процессор (Central Processing Unit, CPU)
       memory: "256Mi" # Оперативная память (Random Access Memory, RAM)
   ```

### Матрица выбора сценария

| Сценарий | Метрика | Основной случай использования |
| :--- | :--- | :--- |
| **Базовый** | CPU | Типичные веб-сервисы с вычислительной нагрузкой |
| **Мультиметрика** | CPU + RAM | Приложения с риском утечки памяти или Java-стек |
| **Внешние метрики** | Kafka/SQS lag | Обработка очередей, фоновые задачи |
| **Настройка поведения** | CPU + Behavior | Критичные API с резкими всплесками трафика |
| **Кастомные метрики** | RPS / Latency | API, где процессор не является узким местом |

## Практические сценарии

### Сценарий 1: Базовый HPA по процессору (CPU)

Используется для большинства веб-приложений (Stateless), где нагрузка напрямую коррелирует с использованием процессора.

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: my-app-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: my-app
  minReplicas: 3
  maxReplicas: 20
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 60
```

### Сценарий 2: Мультиметрика (CPU и Память)

HPA вычисляет необходимое количество реплик для каждой метрики отдельно и выбирает **наибольшее** значение из полученных результатов.

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: multi-metric-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: memory-heavy-app
  minReplicas: 2
  maxReplicas: 10
  metrics:
    - type: Resource
      resource: { name: cpu, target: { type: Utilization, averageUtilization: 50 } }
    - type: Resource
      resource: { name: memory, target: { type: Utilization, averageUtilization: 80 } }
```

### Сценарий 3: Масштабирование по длине очереди (Внешние метрики)

Для использования внешних метрик требуется специальный адаптер, например **[KEDA](../keda/keda_concepts.md)**. Подробнее об архитектуре работы с очередями см. в разделе **[Паттерн Workers + Queue](../workers_queue_pattern.md)**.

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: queue-based-hpa
spec:
  scaleTargetRef: { apiVersion: apps/v1, kind: Deployment, name: worker }
  minReplicas: 1
  maxReplicas: 50
  metrics:
    - type: External
      external:
        metric: { name: queue_messages_ready }
        target: { type: AverageValue, averageValue: "200" }
```

### Сценарий 4: Тонкая настройка поведения (Behavior)

Данный сценарий позволяет настроить «агрессивность» масштабирования. Например, быстро расти при пиках и медленно сокращаться для обеспечения стабильности (предотвращение дребезга).

```yaml
spec:
  behavior:
    scaleUp:
      stabilizationWindowSeconds: 0 # Мгновенная реакция на рост
      policies:
        - type: Percent
          value: 100
          periodSeconds: 15
    scaleDown:
      stabilizationWindowSeconds: 300 # Ожидание 5 минут перед сжатием
      policies:
        - type: Percent
          value: 10
          periodSeconds: 60
```

## Дополнительная информация

Для диагностики и решения проблем со сценариями (например, ошибка `FailedGetResourceMetric`) обратитесь к разделу **[Диагностика и ограничения (hpa_advanced.md)](./hpa_advanced.md)**.

---

**Связанные документы:**

- **[HPA: Главная](./index.md)** — обзор и ключевые определения
- **[Основные концепции](./hpa_concepts.md)** — алгоритм и типы метрик
- **[Паттерн Workers + Queue](../workers_queue_pattern.md)** — архитектура асинхронной обработки
