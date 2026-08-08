# HPA: Практические сценарии

В данном документе представлены типовые конфигурации (YAML-манифесты) горизонтального масштабирования подов (Horizontal Pod Autoscaler, HPA) для различных типов нагрузки в Kubernetes.

## Определения

Для получения вводной информации см. основной раздел **[HPA: Главная](./index.md)**.

**HPA v2 API (`autoscaling/v2`)** — текущая стабильная версия интерфейса, поддерживающая кастомные и внешние метрики, а также тонкую настройку поведения (`behavior`).

**Metrics-driven Scaling** — подход к масштабированию, при котором количество реплик определяется внешними или внутренними показателями производительности, а не только статичным расчетом ресурсов.

## Базовые концепции

### Версии API в манифестах

В современных кластерах Kubernetes (начиная с версии 1.23) единственной рекомендуемой и полностью поддерживаемой версией API является `autoscaling/v2`. Версии `v2beta1` и `v2beta2` объявлены устаревшими (deprecated) и удалены в новых релизах. Версия `v1` поддерживает только масштабирование по CPU и считается ограниченной. Все манифесты в данном документе используют современный стандарт `autoscaling/v2`.

### Предварительные требования

Для успешного применения любого из сценариев ниже необходимо выполнение двух условий:

1. **Metrics Server:** должен быть развернут в кластере для сбора данных о потреблении ресурсов (ЦПУ/Память).
2. **Resource Requests:** HPA использует запросы ресурсов (`requests`) в спецификации пода как базовую линию для расчета процента утилизации. Без них расчет в процентах невозможен, и статус HPA будет `<unknown>`.

   ```yaml
   resources:
     requests:
       cpu: "200m"
       memory: "256Mi"
   ```

### Алгоритм внедрения

1. **Определите метрики и цели:** Выберите показатели для наблюдения.
2. **Наблюдение и настройка:** После деплоя отслеживайте реакцию HPA. При необходимости скорректируйте пороги или используйте поле `behavior` для управления скоростью масштабирования.
3. **Изучите пользовательские метрики:** Если стандартных ресурсов недостаточно, настройте интеграцию с KEDA для автомасштабирования на основе бизнес-логики.

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
      resource: 
        name: cpu
        target: 
          type: Utilization
          averageUtilization: 50
    - type: Resource
      resource: 
        name: memory
        target: 
          type: Utilization
          averageUtilization: 80
```

### Сценарий 3: Масштабирование по длине очереди (Внешние метрики)

Для использования внешних метрик требуется специальный адаптер, например **KEDA**. Подробнее об архитектуре работы с очередями см. в разделе **[Паттерн Workers + Queue](../workers_queue_pattern.md)**.

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: queue-based-hpa
spec:
  scaleTargetRef: 
    apiVersion: apps/v1
    kind: Deployment
    name: worker
  minReplicas: 1
  maxReplicas: 50
  metrics:
    - type: External
      external:
        metric: 
          name: queue_messages_ready
        target: 
          type: AverageValue
          averageValue: "200"
```

### Сценарий 4: Тонкая настройка поведения (Behavior)

Данный сценарий позволяет настроить «агрессивность» масштабирования. Например, быстро расти при пиках и медленно сокращаться для обеспечения стабильности (предотвращение дребезга).

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: behavior-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: critical-api
  minReplicas: 3
  maxReplicas: 15
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 70
  behavior:
    scaleUp:
      stabilizationWindowSeconds: 0 # Мгновенная реакция на рост
      policies:
        - type: Percent
          value: 100 # Рост на 100% за раз
          periodSeconds: 15
    scaleDown:
      stabilizationWindowSeconds: 300 # Ожидание 5 минут перед сжатием
      policies:
        - type: Percent
          value: 10 # Уменьшение только на 10%
          periodSeconds: 60
```

## Дополнительная информация

Для диагностики и решения проблем со сценариями (например, ошибка `FailedGetResourceMetric`, `<unknown>` таргеты) всегда обращайтесь к документу по продвинутой настройке.

### См. также

- **[Продвинутые темы и тонкая настройка](./hpa_advanced.md)** — диагностика проблем и детальный разбор Behavior.
- **[KEDA: Основные концепции](../keda/keda_concepts.md)** — событийное автомасштабирование по внешним метрикам (до нуля).
- **[Metrics Server](../../MonitoringLogging/metrics-server.md)** — источник метрик для работы API v2.
