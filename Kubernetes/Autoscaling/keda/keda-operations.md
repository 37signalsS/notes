# KEDA: Эксплуатация — мониторинг и troubleshooting

## Определения и базовые концепции

Данный материал посвящен промышленной эксплуатации KEDA: диагностике неисправностей, мониторингу с алертами и решению типовых проблем.

Смежные материалы:

* **[KEDA: Основные концепции](./keda_concepts.md)** — архитектура, компоненты, глоссарий
* **[KEDA: Практические сценарии](./practical_scenarios.md)** — установка и конфигурация триггеров
* **[KEDA: FinOps-гардрейлы и измерение экономии](./keda-finops.md)** — экономика масштабирования

## Диагностика и отладка

Основные команды для проверки состояния:

```bash
# Проверка статуса всех ресурсов масштабирования
kubectl get scaledobject,scaledjob -A

# Детальная информация о причинах сбоя масштабирования
kubectl describe scaledobject <name> -n <namespace>
# Смотрим на поля:
# - Status.Conditions — есть ли ошибки
# - Status.ScaleTargetKind — правильный ли target
# - Events — что происходило недавно

# Просмотр созданного нативного HPA
kubectl get hpa -n <namespace>
kubectl describe hpa keda-hpa-<name> -n <namespace>
# Проверяем: Current metrics, Desired vs Current replicas, Conditions

# События в namespace
kubectl get events -n <namespace> --sort-by='.lastTimestamp' | tail -20
```

Логи компонентов KEDA:

```bash
kubectl logs -n keda deployment/keda-operator -f
kubectl logs -n keda deployment/keda-metrics-apiserver -f
```

Проверка доступности источника метрик изнутри кластера:

```bash
# Для Prometheus scaler
kubectl run -it --rm debug --image=curlimages/curl --restart=Never -- \
  curl "http://prometheus.monitoring.svc:9090/api/v1/query?query=your_query"

# Для RabbitMQ scaler (management API)
kubectl run -it --rm debug --image=curlimages/curl --restart=Never -- \
  curl "http://user:pass@rabbitmq.app.svc:15672/api/queues/%2F/orders"
```

## Мониторинг KEDA в production

Внедрять KEDA без мониторинга — значит летать вслепую: автоскейлер может молча перестать получать метрики или упереться в лимит реплик.

Ключевые метрики оператора в Prometheus:

```text
keda_scaler_active                # Количество активных ScaledObjects
keda_scaledobject_replicas        # Текущее количество реплик
keda_scaledobject_max_replicas    # Максимальное количество реплик (из spec)
keda_scaler_metrics_value         # Текущее значение метрики скейлера
rate(keda_scaler_errors_total[5m])  # Ошибки скейлера
keda_scaler_metrics_latency       # Latency проверки скейлера
```

Обязательные алерты.

**1. Упор в maxReplicaCount:**

```yaml
- alert: KEDAMaxReplicasReached
  expr: keda_scaledobject_replicas >= keda_scaledobject_max_replicas
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "ScaledObject {{ $labels.scaledobject }} reached maxReplicaCount"
    description: "Workload hit the ceiling. Check if queue/load is growing."
```

**2. Ошибки скейлера:**

```yaml
- alert: KEDAScalerErrors
  expr: rate(keda_scaler_errors_total[5m]) > 0
  for: 2m
  labels:
    severity: critical
  annotations:
    summary: "KEDA scaler {{ $labels.scaler }} has errors"
    description: "KEDA cannot fetch metrics. Autoscaling may be broken."
```

**3. Рост очереди при максимальных репликах:**

```yaml
- alert: QueueGrowingAtMaxScale
  expr: |
    keda_scaler_metrics_value{scaler="rabbitmq"} > 1000
    and
    keda_scaledobject_replicas >= keda_scaledobject_max_replicas
  for: 10m
  labels:
    severity: critical
  annotations:
    summary: "Queue growing but already at max replicas"
    description: "Need to increase maxReplicaCount or optimize workers."
```

**4. Долгий cold start:**

```yaml
- alert: SlowColdStart
  expr: |
    avg_over_time(keda_scaledobject_replicas[5m]) == 0
    and
    avg_over_time(some_app_request_duration_seconds[5m]) > 30
  for: 5m
  annotations:
    summary: "Cold start taking too long"
    description: "App scaled from 0 but startup is slow. Check image size, probes."
```

## Типичные проблемы и решения

### Проблема 1: Cold start съедает SLA

Первый запрос после scale-to-zero ждет 30+ секунд. Причины: большой Docker-образ, долгая инициализация приложения, warm-up connection pool базы данных, загрузка конфигов/секретов.

Решения:

а) Если задержка критична — отключить scale-to-zero:

```yaml
minReplicaCount: 1  # вместо 0
```

б) Оптимизировать образ (пример multi-stage build для Python):

```dockerfile
# Multi-stage build
FROM python:3.11-slim as builder
RUN pip install --user package1 package2

FROM python:3.11-slim
COPY --from=builder /root/.local /root/.local
COPY app.py .
CMD ["python", "app.py"]

# Результат: образ 150MB вместо 800MB
# Cold start: 8 секунд вместо 25
```

в) Настроить readiness probe так, чтобы трафик не попадал в неготовый под:

```yaml
readinessProbe:
  httpGet:
    path: /health
    port: 8080
  initialDelaySeconds: 10
  periodSeconds: 2
  failureThreshold: 3
```

г) Для HTTP Add-on — буферизация: Interceptor удерживает запросы в очереди, пока поды поднимаются.

### Проблема 2: Очередь растет быстрее, чем scale up

Сообщения прибывают со скоростью 1000/сек, а поды поднимаются ~30 сек — очередь растет быстрее, чем обрабатывается.

Решения:

а) Уменьшить `pollingInterval`:

```yaml
pollingInterval: 10  # вместо 30
```

б) Увеличить `maxReplicaCount` с запасом.

в) Включить агрессивную политику scale up:

```yaml
advanced:
  horizontalPodAutoscalerConfig:
    behavior:
      scaleUp:
        stabilizationWindowSeconds: 0
        policies:
          - type: Percent
            value: 100
            periodSeconds: 15
```

г) Проверить лимиты downstream: если база данных выдерживает только 100 connections, а каждый под держит 10, то больше 10 подов означают ошибки подключения. Решения на стороне зависимости: увеличить connection pool базы, оптимизировать использование соединений в коде, использовать connection pooler (PgBouncer).

### Проблема 3: Flapping — поды создаются и удаляются каждые пару минут

Нагрузка колеблется вокруг порога:

```text
10:00 - 5 pods
10:02 - 3 pods
10:04 - 5 pods
10:06 - 3 pods
```

Решения:

а) Увеличить `cooldownPeriod`:

```yaml
cooldownPeriod: 600  # 10 минут вместо 5
```

б) Использовать stabilization window:

```yaml
advanced:
  horizontalPodAutoscalerConfig:
    behavior:
      scaleDown:
        stabilizationWindowSeconds: 600
```

в) Пересмотреть порог в сторону более грубой гранулярности:

```yaml
value: "20"  # вместо чувствительных "10"
```

### Проблема 4: KEDA не видит метрику из Prometheus

ScaledObject в статусе показывает ошибку вида `error getting metric: query returned no data`.

Решения:

а) Проверить query вручную:

```bash
kubectl run -it --rm debug --image=curlimages/curl --restart=Never -- \
  curl "http://prometheus.monitoring.svc:9090/api/v1/query?query=sum(rate(http_requests_total[2m]))"
```

б) Проверить формат результата — KEDA требует scalar или vector с одним элементом:

```json
// Правильно:
{"data": {"result": [{"value": [1234567890, "42.5"]}]}}

// Неправильно (несколько элементов):
{"data": {"result": [
  {"metric": {"pod": "api-1"}, "value": [1234567890, "10"]},
  {"metric": {"pod": "api-2"}, "value": [1234567890, "15"]}
]}}
```

в) Добавить агрегацию:

```promql
# Было
rate(http_requests_total{deployment="api"}[2m])
# Стало
sum(rate(http_requests_total{deployment="api"}[2m]))
```

г) Проверить доступность Prometheus и корректность `serverAddress` (`kubectl get svc -n monitoring`).

### Проблема 5: Workload постоянно упирается в maxReplicaCount

Нагрузка продолжает расти, хотя лимит достигнут.

Диагностика:

```promql
# Сколько времени workload на максимуме
avg_over_time((keda_scaledobject_replicas == keda_scaledobject_max_replicas)[1h:])

# Растет ли очередь
rate(rabbitmq_queue_messages[5m]) > 0
```

Решения:

а) Увеличить `maxReplicaCount`, если инфраструктура позволяет.
б) Оптимизировать код: профилировать узкие места, уменьшить время обработки одного сообщения, добавить батчинг.
в) Вертикальное масштабирование:

```yaml
resources:
  requests:
    cpu: 500m   # было 200m
    memory: 1Gi # было 512Mi
```

г) Проверить downstream: возможно, проблема не в воркерах, а в базе данных или внешнем API.

Методика выбора значения `maxReplicaCount` и финансовая сторона лимитов описаны в [KEDA: FinOps-гардрейлы и измерение экономии](./keda-finops.md).

## См. также

* **[KEDA: Практические сценарии](./practical_scenarios.md)** — установка и конфигурация триггеров
* **[KEDA: FinOps-гардрейлы и измерение экономии](./keda-finops.md)** — пилот и замер эффекта
* **[Horizontal Pod Autoscaler (HPA): Практические сценарии](../HPA/hpa_scenarios.md)** — стандартное масштабирование
