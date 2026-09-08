# HPA: Практические сценарии

В данном документе представлены типовые конфигурации (YAML-манифесты) горизонтального масштабирования подов (Horizontal Pod Autoscaler, HPA) для различных типов нагрузки в Kubernetes, а также пошаговые инструкции по их внедрению и валидации.

Для получения вводной информации см. основной раздел **[HPA: Главная](./index.md)**. Теоретические основы (алгоритм, типы метрик, архитектура) описаны в **[HPA: Основные концепции](./hpa_concepts.md)**. Продвинутая настройка и тонкая диагностика — в **[HPA: Продвинутые темы](./hpa_advanced.md)**.

## Определения

**HPA v2 API (`autoscaling/v2`)** — текущая стабильная версия интерфейса (GA с Kubernetes 1.23), поддерживающая кастомные и внешние метрики, несколько метрик в одном HPA, а также тонкую настройку поведения (`behavior`). Версии `v2beta1` и `v2beta2` удалены начиная с Kubernetes 1.26. Версия `v1` поддерживает только масштабирование по CPU и считается ограниченной.

**Metrics-driven Scaling** — подход к масштабированию, при котором количество реплик определяется внешними или внутренними показателями производительности, а не только статичным расчетом ресурсов. HPA реализует этот подход через петлю управления (Control Loop), опрашивающую API метрик каждые 15 секунд.

**ScaleTargetRef** — ссылка на объектDeployment, ReplicaSet или StatefulSet — который управляет масштабированием. HPA изменяет поле `replicas` через `/scale` подресурс этого объекта. При использовании Deployment необходимо ссылаться на Deployment, а не на ReplicaSet, иначе при Rollout HPA может масштабировать старый (неактивный) ReplicaSet.

**Resource Requests** — гарантированный объем ресурсов (CPU, памяти), зарезервированных для контейнера. HPA использует `requests` как базовую линию для расчета процента утилизации: `(текущее_потребление / requests) × 100%`. Без `requests` расчет невозможен, статус HPA будет `<unknown>`.

**Behavior** — секция в спецификации HPA v2, позволяющая тонко настраивать политики и скорость масштабирования вверх (`scaleUp`) и вниз (`scaleDown`), включая управление окнами стабилизации и приоритетами политик.

## Предварительные требования

Для успешного применения любого из сценариев ниже необходимо выполнение следующих условий:

1. **Metrics Server:** должен быть развернут в кластере для сбора данных о потреблении ресурсов (CPU/память). Проверка:
   ```bash
   kubectl get deployment metrics-server -n kube-system
   kubectl top nodes
   ```

2. **Resource Requests:** HPA использует `requests` в спецификации контейнера как базовую линию для расчета процента утилизации. Без них статус HPA будет `<unknown>`. Пример:
   ```yaml
   resources:
     requests:
       cpu: "200m"
       memory: "256Mi"
   ```

3. **Готовые поды (Ready Pods):** HPA учитывает только поды в состоянии `Ready`. Если поды долго стартуют или падают (CrashLoop), расчеты будут неточными. Убедитесь, что `readinessProbe` настроен корректно.

4. **Адаптер метрик (для кастомных/внешних метрик):** Для масштабирования по RPS, длине очереди или другим нетривиальным метрикам необходим Prometheus Adapter или **[KEDA](../keda/keda_concepts.md)**.

## Алгоритм внедрения

Пошаговый чек-лист для внедрения HPA в production:

1. **Определите метрики и цели:**
   - Какой показатель лучше всего отражает нагрузку на приложение? (CPU, RPS, длина очереди, задержка)
   - Какой процент утилизации является целевым? (обычно 50-70% для CPU)

2. **Создайте Deployment с `requests`:**
   - Убедитесь, что все контейнеры (включая sidecar) имеют заданные `resources.requests`

3. **Примените HPA и наблюдайте:**
   - После деплоя отслеживайте реакцию HPA в реальном времени через `kubectl get hpa -w`
   - Проверяйте, что TARGETS отображает процент (а не `<unknown>`)

4. **Настройте `behavior` для production:**
   - Агрессивный рост при пиках (`scaleUp` = мгновенно)
   - Медленное сжатие для стабильности (`scaleDown` = окно стабилизации 300-600с)

5. **Добавьте PDB:**
   - Обязательно создайте **Pod Disruption Budget** для защить доступность при масштабировании вниз

6. **Изучите кастомные метрики:**
   - Если стандартных ресурсов недостаточно, настройте интеграцию с KEDA

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

**Параметры:**
- `averageUtilization: 60` — HPA стремится поддерживать среднее потребление CPU на уровне 60% от `requests.cpu`. При превышении этого порога (с учетом толерантности ±10%) происходит масштабирование вверх.
- `minReplicas: 3` — минимальное количество реплик. HPA никогда не опустится ниже этого значения, даже если нагрузка упала до нуля.
- `maxReplicas: 20` — максимальное количество реплик. Защищает от бесконечного роста при аномальных метриках.

### Сценарий 2: Мультиметрика (CPU и Память)

HPA вычисляет необходимое количество реплик для каждой метрики отдельно и выбирает **наибольшее** значение из полученных результатов. Это гарантирует, что ни одна из метрик не будет проигнорирована.

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

**Логика расчета (пример):**
```
Метрика 1 (CPU): 2 реплики × (70% / 50%) = ceil(2.8) = 3 реплики
Метрика 2 (Memory): 2 реплики × (60% / 80%) = ceil(1.5) = 2 реплики

HPA выберет 3 реплики (наибольшее значение)
```

**Важно:** Память как метрика масштабирования имеет особенность — многие среды (JVM, Go) не возвращают память ОС мгновенно после GC. Метрика `working_set_bytes` остается высокой, и HPA может «застревать» на максимальных репликах. Используйте память как ограничение безопасности, а не основную метрику.

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

**Параметры:**
- `type: External` — метрика находится за пределами кластера (очередь RabbitMQ, Kafka, база данных).
- `averageValue: "200"` — целевое среднее значение метрики на один под. Если очередь содержит 1000 сообщений, HPA запросит `ceil(1000 / 200) = 5` реплик.
- Адаптер (KEDA, Prometheus Adapter) предоставляет метрику через External Metrics API (`external.metrics.k8s.io`).

### Сценарий 4: Масштабирование по нагрузке на инстанс (Pods метрики)

Используется, когда метрика привязана к конкретному поду (RPS на инстанс, размер локального кэша, количество активных соединений).

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: rps-based-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: api-gateway
  minReplicas: 2
  maxReplicas: 20
  metrics:
    - type: Pods
      pods:
        metric:
          name: http_requests_per_second
        target:
          type: AverageValue
          averageValue: "500"
```

**Параметры:**
- `type: Pods` — метрика является индивидуальной для каждого пода. HPA делит общее значение метрики на количество готовых подов.
- `averageValue: "500"` — целевое количество запросов в секунду на один под. Если общая нагрузка 5000 RPS, HPA запросит `ceil(5000 / 500) = 10` реплик.
- Требует адаптера метрик (Prometheus Adapter), настроенного на сбор метрики `http_requests_per_second` из Prometheus.

### Сценарий 5: Масштабирование по метрике объекта (Object метрики)

Используется, когда метрика является общей для всех подов (общая нагрузка на Ingress, количество активных Job, размер очереди в MongoDB).

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: ingress-based-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: backend
  minReplicas: 2
  maxReplicas: 15
  metrics:
    - type: Object
      object:
        describedObject:
          apiVersion: networking.k8s.io/v1
          kind: Ingress
          name: main-ingress
        metric:
          name: requests_per_second
        target:
          type: Value
          value: "1000"
```

**Параметры:**
- `type: Object` — метрика привязана к другому объекту Kubernetes (Ingress, Job, Service).
- `target.type: Value` — абсолютное значение для всего объекта. HPA сравнивает общее значение метрики с целевым напрямую (без деления на количество подов).
- Если Ingress обрабатывает 3000 RPS, а цель — 1000 RPS, HPA запросит `ceil(3000 / 1000) = 3` реплики.

### Сценарий 6: Тонкая настройка поведения (Behavior)

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

**Параметры `behavior`:**

| Поле | Описание | Рекомендации |
|:---|:---|:---|
| `stabilizationWindowSeconds` | Период анализа исторических метрик. Для `scaleDown` HPA выбирает **наибольшее** (наиболее безопасное) количество реплик за окно. | `scaleUp`: 0 (мгновенно), `scaleDown`: 300-600 (5-10 минут). |
| `policies.type` | Тип политики: `Percent` (процент от текущих реплик) или `Pods` (абсолютное количество). | `Percent` для масштабных приложений, `Pods` для малых deployments. |
| `policies.value` | Максимальное изменение за один шаг. Для `Percent: 100` — удвоение за раз. | `scaleUp`: 100-200 (быстрый рост), `scaleDown`: 10-25 (осторожное сжатие). |
| `policies.periodSeconds` | Интервал между шагами масштабирования. | `scaleUp`: 15-60, `scaleDown`: 60-120. |

**Дополнительные параметры `behavior`:**

- `selectPolicy: Max` (по умолчанию) — выбирает политику, дающую **наибольшее** количество реплик. Для `scaleUp` — агрессивный рост, для `scaleDown` — консервативное сжатие.
- `selectPolicy: Min` — выбирает политику, дающую **наименьшее** количество реплик. Для `scaleUp` — консервативный рост, для `scaleDown` — агрессивное сжатие.
- `selectPolicy: Disabled` — полностью отключает масштабирование в данном направлении.

Подробнее о поведении см. **[HPA: Продвинутые темы — Behavior](./hpa_advanced.md#tonkaya-nastroyka-behavior)**.

### Сценарий 7: Масштабирование по ресурсу конкретного контейнера (ContainerResource)

Позволяет масштабировать по ресурсам конкретного контейнера в поде, игнорируя потребление sidecar-контейнеров (Envoy, fluent-bit, telegraf), которые могут искажать общую картину утилизации.

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: container-resource-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: my-app
  minReplicas: 2
  maxReplicas: 10
  metrics:
    - type: ContainerResource
      containerResource:
        container: main-app
        name: cpu
        target:
          type: Utilization
          averageUtilization: 70
```

**Параметры:**
- `container: main-app` — имя контейнера, по ресурсам которого происходит масштабирование. Sidecar-контейнеры (Envoy, fluent-bit) игнорируются.
- `name: cpu` — ресурс для мониторинга. Также поддерживается `memory`.
- Контейнер `main-app` должен иметь `resources.requests.cpu`, иначе расчет утилизации невозможен.

**Когда использовать:**
- В поде есть sidecar, потребляющий значительную долю ресурсов (Envoy proxy — до 100m CPU).
- Sidecar «съедает» часть лимита и искажает общую утилизацию пода.
- Стандартный `Resource` метрик показывает высокое потребление, хотя приложение нагружено минимально.

Подробнее см. **[HPA: Продвинутые темы — ContainerResource](./hpa_advanced.md#containerresource-masshtabirovanie-po-resursu-konkretnogo-konteynera)**.

### Сценарий 8: HPA для StatefulSet

HPA поддерживает StatefulSets, но с ограничениями. StatefulSets не пересоздают поды при обновлении — HPA изменяет количество реплик через `/scale` подресурс.

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: statefulset-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: StatefulSet
    name: kafka-consumer
  minReplicas: 2
  maxReplicas: 10
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 65
  behavior:
    scaleDown:
      stabilizationWindowSeconds: 600  # 10 минут для StatefulSet
      policies:
        - type: Pods
          value: 1  # Удаляем по одному поду
          periodSeconds: 120
```

**Особенности:**
- StatefulSet имеет стабильные сетевые идентификаторы и постоянные тома. Масштабирование вниз удаляет поды с наименьшим индексом.
- Используйте `policies.type: Pods` с `value: 1` для масштабирования вниз — это гарантирует последовательное удаление подов и минимальное влияние на состояние.
- Увеличенное `stabilizationWindowSeconds` (600с) для scaleDown защищает от случайного удаления подов с данными.

### Сценарий 9: HPA + PDB (связка для production)

Pod Disruption Budget (PDB) защищает доступность сервиса при масштабировании вниз. HPA учитывает PDB, но при агрессивном `scaleDown` масштабирование может «застревать».

```yaml
# PDB: минимум 2 пода всегда доступны
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: my-app-pdb
spec:
  minAvailable: 2
  selector:
    matchLabels:
      app: my-app
---
# HPA: осторожное масштабирование вниз
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
  maxReplicas: 15
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 60
  behavior:
    scaleDown:
      stabilizationWindowSeconds: 300
      policies:
        - type: Pods
          value: 1  # Удаляем по одному поду
          periodSeconds: 60
```

**Проверка PDB:**
```bash
# Просмотр PDB для сервиса
kubectl get pdb my-app-pdb

# Проверка, разрешит ли PDB удаление подов
kubectl get pdb my-app-pdb -o jsonpath='{.status.currentHealthy}' # → 3
kubectl get pdb my-app-pdb -o jsonpath='{.status.disruptionsAllowed}' # → 1
```

**Взаимодействие:**
- PDB с `minAvailable: 2` при 3 репликах разрешает удаление только 1 пода за раз.
- HPA с `policies.type: Pods, value: 1` удаляет по одному поду — PDB не блокирует операцию.
- Если HPA попытается удалить 2 пода одновременно, PDB заблокирует второе удаление.

Подробнее: **[Pod Disruption Budget](../pod_disruption_budget.md)**.

### Сценарий 10: Комбинированные политики Behavior

Несколько политик в одном блоке `behavior` с `selectPolicy` для управления приоритетом.

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: combined-behavior-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: payment-service
  minReplicas: 3
  maxReplicas: 30
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 60
  behavior:
    scaleUp:
      stabilizationWindowSeconds: 0
      policies:
        - type: Percent
          value: 100  # Удвоение за раз
          periodSeconds: 15
        - type: Pods
          value: 4   # Или 4 пода за раз
          periodSeconds: 15
      selectPolicy: Max  # Выбирает более агрессивную политику
    scaleDown:
      stabilizationWindowSeconds: 600
      policies:
        - type: Percent
          value: 10
          periodSeconds: 60
        - type: Pods
          value: 1
          periodSeconds: 60
      selectPolicy: Min  # Выбирает более консервативную политику
```

**Логика `selectPolicy`:**
- `scaleUp` + `selectPolicy: Max`: Если политика Percent дает 6 подов, а Pods — 4 пода, HPA выберет 6 (более агрессивный рост).
- `scaleDown` + `selectPolicy: Min`: Если политика Percent дает уменьшение на 3 пода, а Pods — на 1 под, HPA выберет 1 (более консервативное сжатие).

## Валидация

После применения HPA необходимо убедиться, что он работает корректно:

```bash
# 1. Проверка текущего состояния HPA
kubectl get hpa my-app-hpa
# → NAME           REFERENCE          TARGETS   MINPODS   MAXPODS   REPLICAS   AGE
# → my-app-hpa     Deployment/my-app  35%/60%   3         20        3          5m
```

**Ожидаемый результат:** В колонке `TARGETS` отображается процент утилизации (например, `35%/60%`), а не `<unknown>`.

```bash
# 2. Детальная информация (условия и события)
kubectl describe hpa my-app-hpa

# 3. Проверка конкретного условия ScalingActive
kubectl get hpa my-app-hpa -o jsonpath='{.status.conditions[?(@.type=="ScalingActive")].status}'
# → True (метрики собираются) или False (проблема)

# 4. Просмотр текущего потребления ресурсов
kubectl top pods -l app=my-app
# → NAME                     CPU(cores)   MEMORY(bytes)
# → my-app-6d4f5b5c7-x2j9k  120m         180Mi

# 5. Мониторинг в реальном времени (ожидание масштабирования)
kubectl get hpa my-app-hpa -w
```

**Если TARGETS = `<unknown>`:**
1. Проверьте наличие `resources.requests` у всех контейнеров: `kubectl get pod <pod> -o jsonpath='{.spec.containers[*].resources.requests}'`
2. Проверьте доступность Metrics Server: `kubectl top nodes`
3. Проверьте условия HPA: `kubectl describe hpa my-app-hpa` (раздел Conditions)

Детальная диагностика: [Устранение неполадок HPA](../../Troubleshooting/Common_Errors/hpa_troubleshooting.md).

## Типовые ошибки

| Ошибка | Причина | Решение |
|:---|:---|:---|
| `TARGETS` показывает `<unknown>` | Отсутствуют `requests` у контейнеров или Metrics Server недоступен. | Добавить `resources.requests` всем контейнерам, установить Metrics Server. |
| HPA не масштабирует вниз | Метрики не падают ниже порога толерантности или достигнут `minReplicas`. | Проверить фактическое потребление: `kubectl top pods`. Уменьшить `minReplicas`. |
| HPA не масштабирует вверх | Метрики стабильны в пределах толерантности (±10% от целевого значения). | Проверить, что нагрузка действительно растет. Увеличить `maxReplicas`. |
| Дребезг (flapping) | Частое переключение между масштабированием вверх и вниз. | Настроить `behavior` с окном стабилизации для `scaleDown`. Увеличить `maxReplicas`. |
| Конфликт с ручным `kubectl scale` | HPA перезаписывает вручную заданные `replicas`. | Управлять масштабированием только через HPA. Не использовать `kubectl scale`. |
| `<unknown>` при работающем Metrics Server | У sidecar-контейнера отсутствуют `requests`. HPA требует `requests` для **всех** контейнеров. | Добавить `requests` sidecar или использовать тип метрики `ContainerResource`. |
| PDB блокирует scale-down | PDB требует `minAvailable`, превышающее количество реплик после масштабирования. | Ослабить PDB или настроить `behavior.scaleDown` с policies.type: Pods, value: 1. |

## Граничные случаи (Edge Cases)

1. **Масштабирование при обновлении Deployment:** При Rollout Deployment создается новый ReplicaSet. HPA начинает масштабировать новый ReplicaSet только после того, как поды из него становятся `Ready`. Если `scaleTargetRef` указывает на ReplicaSet (а не на Deployment), HPA может масштабировать неактивный ReplicaSet.

2. **HPA и DaemonSet:** HPA **не поддерживается** для DaemonSet, так как DaemonSet гарантирует ровно один под на каждом узле. Масштабирование регулируется количеством узлов в кластере.

3. **HPA и Job/CronJob:** HPA обычно **не применяется** к Job и CronJob, так как эти объекты имеют конечный жизненный цикл. Для масштабирования воркеров в очередях используйте KEDA.

4. **Множественные HPA на один объект:** Kubernetes **не запрещает** создание нескольких HPA на один Deployment, но это приводит к непредсказуемому поведению — каждый HPA независимо рассчитывает целевое количество реплик и конфликтует за право записи в `/scale`. Рекомендация: **один HPA на объект**.

5. **Отсутствие метрик при масштабировании вниз:** Если Metrics Server временно недоступен, HPA **не уменьшает** количество реплик — он сохраняет текущее состояние до восстановления доступа к метрикам. Это защитный механизм.

6. **Очень маленький `maxReplicas`:** Диапазон `min=1, max=2` лишает HPA математического смысла — формула `ceil(1 × (метрика / цель))` практически всегда даст 1 или 2, и HPA будет постоянно «застревать» на лимитах. Рекомендуется `maxReplicas >= 5`.

7. **Нулевое потребление метрик:** Если все поды потребляют 0% ресурсов (приложение простаивает), HPA рассчитает `ceil(3 × (0 / 50)) = 0`. Однако `minReplicas` не позволит опуститься ниже заданного минимума. Для масштабирования до нуля используйте KEDA.

8. **Два типа `value` для одной метрики:** Нельзя задавать одновременно `averageUtilization` и `averageValue` для одной метрики в одном HPA. Используйте либо `Utilization` (процент от requests), либо `AverageValue` (абсолютное значение).

## Лучшие практики

1. **Начинайте с CPU:** Для stateless-приложений CPU является наиболее надежным и предсказуемым показателем нагрузки.
2. **Настраивайте `behavior`:** Для продакшена всегда определяйте политики scaleUp/scaleDown. Агрессивный рост при пиках и медленное сжатие — типичный паттерн.
3. **Используйте PDB:** Обязательно создавайте **Pod Disruption Budget** вместе с HPA. Это гарантирует, что при масштабировании в_DOWN или удалении узлов не будет нарушена доступность сервиса.
4. **Настраивайте Readiness Probes:** HPA учитывает только «готовые» поды. Без настроенных `readinessProbe` HPA может начать масштабирование на основе данных от еще не прогретых подов.
5. **Избегайте узких диапазонов `maxReplicas`:** Слишком маленький диапазон (например, 1-2 реплики) лишает HPA математического смысла и делает его излишне чувствительным к колебаниям.
6. **Не задавайте `replicas` в манифесте:** Если HPA управляет масштабированием — удалите поле `replicas` из Deployment-манителста. Иначе повторный `kubectl apply` перезапишет значение, выставленное HPA.
7. **Память как второстепенная метрика:** Многие среды (JVM, Go) не возвращают память ОС мгновенно после GC, что ведет к «застреванию» HPA на максимальных репликах. Используйте память как ограничение безопасности, а не основную метрику.
8. **Тестируйте в staging:** Перед применением в production протестируйте HPA в staging-среде с реальной нагрузкой. Убедитесь, что масштабирование происходит в ожидаемые сроки и без дребезга.

## Cleanup/Revert

Для отката изменений и очистки ресурсов:

```bash
# Удаление HPA (масштабирование прекращается, количество реплик остается последним)
kubectl delete hpa my-app-hpa

# Удаление PDB
kubectl delete pdb my-app-pdb

# Ручное восстановление количества реплик (если необходимо)
kubectl scale deployment my-app --replicas=3

# Проверка, что HPA удален
kubectl get hpa
# → No resources found
```

**Важно:** При удалении HPA количество реплик **не возвращается** к исходному значению. Оно остается на уровне последнего расчета HPA. Если необходимо вернуть конкретное значение — используйте `kubectl scale`.

### Сценарий 11: HPA + NGINX Ingress Controller (масштабирование по метрикам Ingress)

NGINX Ingress Controller экспортирует метрики Prometheus (через порт 10254 или 9113). Эти метрики можно использовать для масштабирования бэкенд-сервисов.

**Предварительные требования:**
- NGINX Ingress Controller с включенным Prometheus exporter
- Prometheus Adapter или KEDA для предоставления метрик через Custom Metrics API

**Вариант A: HPA по RPS через Prometheus Adapter**

```yaml
# Prometheus Adapter config.yaml (правило для RPS)
config.yaml: |
  rules:
    - seriesQuery: 'nginx_ingress_controller_requests{namespace!="",ingress!=""}'
      resources:
        overrides:
          namespace: {resource: "namespace"}
          ingress: {resource: "ingress", group: "networking.k8s.io", version: "v1"}
      name:
        matches: "^(.*)_requests$"
        as: "requests_per_second"
      metricsQuery: 'sum(rate(<<.Series>>{<<.LabelMatchers>>}[2m])) by (<<.GroupBy>>)'
---
# HPA: масштабирование по RPS на Ingress
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: my-app-ingress-rps-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: my-app
  minReplicas: 2
  maxReplicas: 20
  metrics:
    - type: Object
      object:
        describedObject:
          apiVersion: networking.k8s.io/v1
          kind: Ingress
          name: my-app-ingress
        metric:
          name: requests_per_second
        target:
          type: Value
          value: "1000"  # Общая нагрузка на Ingress
```

**Вариант B: HPA по Latency P99 через Prometheus Adapter**

```yaml
# Prometheus Adapter config.yaml (правило для P99 latency)
config.yaml: |
  rules:
    - seriesQuery: 'nginx_ingress_controller_request_duration_seconds_bucket{namespace!="",ingress!=""}'
      resources:
        overrides:
          namespace: {resource: "namespace"}
          ingress: {resource: "ingress", group: "networking.k8s.io", version: "v1"}
      name:
        matches: "^(.*)_bucket$"
        as: "${1}_p99"
      metricsQuery: 'histogram_quantile(0.99, sum(rate(<<.Series>>{<<.LabelMatchers>>}[5m])) by (le, <<.GroupBy>>))'
---
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: my-app-latency-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: my-app
  minReplicas: 2
  maxReplicas: 15
  metrics:
    - type: Object
      object:
        describedObject:
          apiVersion: networking.k8s.io/v1
          kind: Ingress
          name: my-app-ingress
        metric:
          name: nginx_ingress_controller_request_duration_seconds_p99
        target:
          type: Value
          value: "500m"  # P99 < 500ms
  behavior:
    scaleDown:
      stabilizationWindowSeconds: 300
      policies:
        - type: Pods
          value: 1
          periodSeconds: 60
```

**Вариант C: HPA по RPS через KEDA (рекомендуемый)**

```yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: my-app-keda-scaler
spec:
  scaleTargetRef:
    name: my-app
  minReplicaCount: 2
  maxReplicaCount: 20
  triggers:
    - type: prometheus
      metadata:
        serverAddress: http://prometheus-kube-prometheus-prometheus.monitoring.svc:9090
        metricName: nginx_requests_per_second
        threshold: "1000"
        query: |
          sum(rate(nginx_ingress_controller_requests{
            ingress="my-app-ingress"
          }[2m]))
```

**Проверка метрик NGINX Ingress:**
```bash
# Prometheus метрики NGINX Ingress
kubectl port-forward -n ingress-nginx svc/ingress-nginx-controller 10254:10254
curl http://localhost:10254/metrics | grep nginx_ingress_controller_requests

# Или через Prometheus
kubectl port-forward -n monitoring svc/prometheus 9090:9090
# В Prometheus UI: sum(rate(nginx_ingress_controller_requests[2m])) by (ingress)
```

**Популярные метрики NGINX Ingress для HPA:**

| Метрика | Тип | Применение |
|:---|:---|:---|
| `nginx_ingress_controller_requests` | Counter | RPS, количество запросов по кодам ответа |
| `nginx_ingress_controller_request_duration_seconds` | Histogram | Latency (p50, p95, p99) |
| `nginx_ingress_controller_nginx_process_connections_active` | Gauge | Активные соединения к бэкенду |
| `nginx_ingress_controller_nginx_process_connections_reading` | Gauge | Соединения в состоянии чтения |

### Сценарий 12: HPA + Traefik (масштабирование по метрикам Traefik)

```yaml
# Traefik экспортирует метрики на порту 8080/metrics
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: my-app-traefik-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: my-app
  minReplicas: 2
  maxReplicas: 15
  metrics:
    - type: Object
      object:
        describedObject:
          apiVersion: networking.k8s.io/v1
          kind: Ingress
          name: my-app-ingress
        metric:
          name: traefik_service_requests_total
        target:
          type: Value
          value: "500"
```

**Популярные метрики Traefik для HPA:**

| Метрика | Описание |
|:---|:---|
| `traefik_service_requests_total` | Количество запросов к сервису |
| `traefik_service_request_duration_seconds` | Латентность запросов |
| `traefik_service_open_connections` | Активные соединения |

## Дополнительная информация

Для диагностики и решения проблем со сценариями (например, ошибка `FailedGetResourceMetric`, `<unknown>` таргеты) см. **[Устранение неполадок HPA](../../Troubleshooting/Common_Errors/hpa_troubleshooting.md)**.

### См. также

- **[HPA: Основные концепции](./hpa_concepts.md)** — алгоритм, типы метрик, архитектура.
- **[HPA: Продвинутые темы](./hpa_advanced.md)** — диагностика проблем и детальный разбор Behavior.
- **[KEDA: Основные концепции](../keda/keda_concepts.md)** — событийное автомасштабирование по внешним метрикам (до нуля).
