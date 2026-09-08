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

### Ключевые метрики оператора в Prometheus

```text
# Метрики масштабирования
keda_scaler_active                # Количество активных ScaledObjects
keda_scaledobject_replicas        # Текущее количество реплик
keda_scaledobject_max_replicas    # Максимальное количество реплик (из spec)
keda_scaledobject_ready_replicas  # Количество готовых реплик

# Метрики скейлеров
keda_scaler_metrics_value         # Текущее значение метрики скейлера
keda_scaler_metrics_target        # Целевое значение метрики
keda_scaler_metrics_latency       # Latency проверки скейлера

# Ошибки и здоровье
keda_scaler_errors_total          # Общее количество ошибок скейлера
rate(keda_scaler_errors_total[5m])  # Ошибки скейлера в секунду
keda_operator_errors_total        # Ошибки оператора

# Производительность
keda_scaler_latency               # Время получения метрики
keda_operator_reconcile_duration  # Время согласования
```

### Готовые алерты

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

**5. KEDA Operator не здоров:**

```yaml
- alert: KEDANotHealthy
  expr: up{job="keda-operator"} == 0
  for: 2m
  labels:
    severity: critical
  annotations:
    summary: "KEDA operator is down"
    description: "KEDA operator is not responding. Autoscaling may be broken."
```

**6. Высокая задержка метрик:**

```yaml
- alert: KEDAMetricsLatencyHigh
  expr: histogram_quantile(0.95, rate(keda_scaler_metrics_latency_bucket[5m])) > 10
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "KEDA metrics latency is high"
    description: "Scaler metrics collection is taking too long (>10s)."
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

## Продвинутая диагностика

### Проверка компонентов KEDA

```bash
# Статус всех подов KEDA
kubectl get pods -n keda -o wide

# Детальная информация о поде оператора
kubectl describe pod -l app=keda-operator -n keda

# Проверка readiness и liveness проб
kubectl get pods -n keda -o jsonpath='{.items[*].status.conditions}' | jq .

# Проверка использования ресурсов
kubectl top pods -n keda
```

### Проверка Admission Webhook

```bash
# Проверка наличия webhook
kubectl get validatingwebhookconfigurations | grep keda

# Проверка логов webhook
kubectl logs -n keda deployment/keda-admission-webhooks -f

# Тестирование webhook (если есть ошибки при создании ScaledObject)
kubectl apply -f test-scaledobject.yaml --dry-run=server
```

### Отладка в реальном времени

```bash
# Мониторинг метрик в реальном времени
kubectl port-forward -n keda svc/keda-metrics-server 8080:8080
curl http://localhost:8080/metrics | grep keda_

# Проверка HPA в реальном времени
watch kubectl get hpa -n <namespace>

# Просмотр событий KEDA
kubectl get events -n keda --watch
```

## Анализ задержки масштабирования (scaling latency)

### Этапы задержки

```text
1. Обнаружение события (pollingInterval)
   └── Задержка: 0 до pollingInterval секунд

2. Получение метрики (scaler check)
   └── Задержка: keda_scaler_metrics_latency

3. Рассчёт desired replicas (HPA)
   └── Задержка: ~10 секунд (stabilization window)

4. Создание пода (kube-scheduler)
   └── Задержка: зависит от Image pull, resource availability

5. Инициализация пода (readiness probe)
   └── Задержка: initialDelaySeconds + periodSeconds × failureThreshold
```

### Измерение задержки

```promql
# Время от обнаружения события до создания пода
time() - kube_pod_created{namespace="app"}

# Время готовности пода
kube_pod_status_ready_time - kube_pod_created

# Общая задержка масштабирования
histogram_quantile(0.95, rate(keda_scaler_metrics_latency_bucket[5m]))
```

### Оптимизация задержки

```yaml
# Агрессивная политика масштабирования
advanced:
  horizontalPodAutoscalerConfig:
    behavior:
      scaleUp:
        stabilizationWindowSeconds: 0
        policies:
          - type: Percent
            value: 100
            periodSeconds: 15
      scaleDown:
        stabilizationWindowSeconds: 300
```

## Траблшутинг сетевой политики

### Проблема: KEDA не может подключиться к источнику метрик

Симптомы: `error getting metric: connection refused` или `timeout`

```bash
# Проверка сетевой политики
kubectl get networkpolicies -n keda

# Проверка DNS разрешения из пода KEDA
kubectl exec -n keda deployment/keda-operator -- nslookup prometheus.monitoring.svc

# Проверка доступности сервиса
kubectl exec -n keda deployment/keda-operator -- curl -v http://prometheus.monitoring.svc:9090

# Проверка трафика (если есть CNI с поддержкой flow logs)
kubectl logs -n keda deployment/keda-operator | grep -i "connection\|timeout\|refused"
```

### Решение: Разрешить доступ через NetworkPolicy

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: keda-egress
  namespace: keda
spec:
  podSelector:
    matchLabels:
      app: keda-operator
  policyTypes:
    - Egress
  egress:
    - to:
        - namespaceSelector:
            matchLabels:
              name: monitoring
      ports:
        - protocol: TCP
          port: 9090
    - to:  # DNS
        - namespaceSelector: {}
          podSelector:
            matchLabels:
              k8s-app: kube-dns
      ports:
        - protocol: UDP
          port: 53
```

## Продвинутая работа с Prometheus scaler

### Оптимизация запросов

```promql
# Плохо: высокая кардинальность
rate(http_requests_total{pod=~".*"}[2m])

# Хорошо: агрегация по deployment
sum(rate(http_requests_total{deployment="api"}[2m]))

# Еще лучше: использование recording rules
# В Prometheus создать rule:
# - record: api:request_rate:5m
#   expr: sum(rate(http_requests_total{deployment="api"}[5m]))

# В KEDA использовать:
# query: api:request_rate:5m
```

### Обработка разрывов данных (metric gaps)

```yaml
# Если Prometheus временно недоступен, KEDA может получить пустой результат
# Решение: настроить fallback
fallback:
  failureThreshold: 3
  replicas: 2
  behavior: currentReplicas
```

### Диагностика сложных запросов

```bash
# Тестирование PromQL запроса
kubectl run -it --rm debug --image=curlimages/curl --restart=Never -- \
  curl "http://prometheus.monitoring.svc:9090/api/v1/query" \
  --data-urlencode "query=sum(rate(http_requests_total{deployment=\"api\"}[5m]))"

# Проверка cardinality метрик
kubectl run -it --rm debug --image=curlimages/curl --restart=Never -- \
  curl "http://prometheus.monitoring.svc:9090/api/v1/label/__name__/values"
```

## Масштабирование с несколькими триггерами (multi-trigger)

### Особенности отладки

При нескольких триггерах в ScaledObject KEDA использует MAX логику. Отладка усложняется:

```yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: multi-trigger
spec:
  triggers:
    - type: rabbitmq
      metadata:
        queueLength: "10"
    - type: prometheus
      metadata:
        query: "sum(rate(http_requests_total[5m]))"
        threshold: "100"
```

### Диагностика каждого триггера

```bash
# Проверка метрик всех триггеров
kubectl describe scaledobject multi-trigger -n app

# Смотрим на Status.Conditions:
# - TriggerActive: true/false для каждого триггера
# - CurrentMetrics: текущие значения для каждого триггера

# Проверка логов оператора
kubectl logs -n keda deployment/keda-operator -f | grep -A5 -B5 multi-trigger
```

### Типичные проблемы multi-trigger

```text
1. Конфликтующие триггеры
   - Симптом: масштабирование происходит неожиданно
   - Причина: один триггер требует 0 реплик, другой — 10
   - Решение: проверить activationThreshold для каждого триггера

2. Разная частота опроса
   - Симптом: нестабильное поведение
   - Причина: pollingInterval مختلف для триггеров
   - Решение: установить единый pollingInterval

3. Ошибка в одном триггере блокирует другие
   - Симптом: масштабирование прекращается
   - Причина: fallback не настроен
   - Решение: добавить fallback для каждого триггера
```

## Обновление и миграция KEDA

### Порядок обновления

```bash
# 1. Проверить текущую версию
helm list -n keda

# 2. Обновить репозиторий
helm repo update

# 3. Проверить доступные версии
helm search repo kedacore/keda --versions

# 4. Обновить (с сохранением конфигурации)
helm upgrade keda kedacore/keda \
  --namespace keda \
  --version 2.20.0 \
  --reuse-values

# 5. Проверить статус
kubectl get pods -n keda
kubectl get scaledobject,scaledjob -A
```

### Откат при проблемах

```bash
# 1. Вернуть предыдущую версию
helm rollback keda <REVISION> -n keda

# 2. Проверить статус
kubectl get pods -n keda

# 3. Проверить ScaledObject
kubectl get scaledobject -A
kubectl describe scaledobject <name> -n <namespace>
```

### Проверки после обновления

```bash
# Проверка совместимости API
kubectl api-resources | grep keda

# Проверка CRD
kubectl get crd | grep keda

# Проверка логов на ошибки
kubectl logs -n keda deployment/keda-operator -f | grep -i error

# Тестирование масштабирования
kubectl apply -f test-scaledobject.yaml
kubectl get hpa -n <namespace> -w
```

## Исчерпание ресурсов KEDA Operator

### Симптомы

```text
- KEDA Operator в статусе CrashLoopBackOff
- Метрики перестают обновляться
- ScaledObject не масштабируется
- Ошибки в логах: "out of memory" или "CPU throttling"
```

### Диагностика

```bash
# Проверка использования ресурсов
kubectl top pods -n keda

# Проверка лимитов
kubectl get pod -n keda -o jsonpath='{.items[*].spec.containers[*].resources}'

# Проверка событий OOMKilled
kubectl get events -n keda --field-selector reason=OOMKilling

# Проверка CPU throttling
kubectl get pod -n keda -o jsonpath='{.items[*].status.conditions}' | jq .
```

### Решение

```yaml
# Увеличение ресурсов KEDA Operator
apiVersion: apps/v1
kind: Deployment
metadata:
  name: keda-operator
  namespace: keda
spec:
  template:
    spec:
      containers:
        - name: keda-operator
          resources:
            requests:
              cpu: 200m    # было 100m
              memory: 256Mi  # было 128Mi
            limits:
              cpu: 1000m   # было 500m
              memory: 1Gi   # было 512Mi
```

## Специфика ScaledJob

### Отличия от ScaledObject

```text
ScaledObject:
- Управляет Deployment/StatefulSet
- HPA масштабирует существующие поды
- Поды перезапускаются при масштабировании

ScaledJob:
- Управляет Job
- Создаёт новые Job при масштабировании
- Job завершаются после обработки
```

### Типичные проблемы ScaledJob

```bash
# Проверка статуса Job
kubectl get jobs -n <namespace>

# Проверка логов завершённых Job
kubectl logs job/<job-name> -n <namespace>

# Проверка почему Job не запускаются
kubectl describe scaledjob <name> -n <namespace>
```

### Решение проблем

```yaml
# Проблема: Job создаются, но не запускаются
# Причина: не хватает ресурсов или quota
apiVersion: keda.sh/v1alpha1
kind: ScaledJob
metadata:
  name: batch-processor
spec:
  pollingInterval: 30
  maxReplicaCount: 10
  scalingStrategy:
    strategy: default  # или "custom" для ручной настройки
  jobTargetRef:
    template:
      spec:
        containers:
          - name: processor
            resources:
              requests:
                cpu: 100m
                memory: 128Mi
        restartPolicy: Never
  triggers:
    - type: rabbitmq
      metadata:
        queueLength: "5"
```

## Дашборды для мониторинга KEDA

### Основной дашборд (Grafana)

```json
{
  "panels": [
    {
      "title": "KEDA ScaledObjects Active",
      "targets": [{"expr": "keda_scaler_active"}],
      "type": "stat"
    },
    {
      "title": "Replicas vs Max",
      "targets": [
        {"expr": "keda_scaledobject_replicas", "legendFormat": "Current"},
        {"expr": "keda_scaledobject_max_replicas", "legendFormat": "Max"}
      ],
      "type": "timeseries"
    },
    {
      "title": "Scaler Errors Rate",
      "targets": [{"expr": "rate(keda_scaler_errors_total[5m])"}],
      "type": "timeseries"
    },
    {
      "title": "Metrics Latency P95",
      "targets": [{"expr": "histogram_quantile(0.95, rate(keda_scaler_metrics_latency_bucket[5m]))"}],
      "type": "timeseries"
    }
  ]
}
```

### Готовые дашборды

- **KEDA Operator Dashboard**: https://grafana.com/grafana/dashboards/16880
- **KEDA Scaler Dashboard**: https://grafana.com/grafana/dashboards/16881

## Чек-лист production-развёртывания

### До развёртывания

```text
□ Установлен и настроен Prometheus
□ Настроены алерты (минимум 4 базовых)
□ Настроен Grafana дашборд
□ KEDA установлен в отдельный namespace
□ Настроены RBAC разрешения
□ Настроены Network Policies
□ Тестовые ScaledObject работают в dev/staging
```

### После развёртывания

```text
□ Все поды KEDA в Running статусе
□ Метрики поступают в Prometheus
□ Алерты протестированы (инжектнутые ошибки)
□ Мониторинг 24/7 первый неделю
□ Документация для on-call команды
□ Runbook для типовых проблем
```

## См. также

* **[KEDA: Основные концепции](./keda_concepts.md)** — архитектура, компоненты, глоссарий
* **[KEDA: Практические сценарии](./practical_scenarios.md)** — установка и конфигурация триггеров
* **[KEDA + Kafka](./kafka-keda-scaler.md)** — масштабирование по consumer lag
* **[KEDA + Redis](./redis-keda-scaler.md)** — масштабирование по длине очереди/стрима
* **[KEDA: FinOps-гардрейлы и измерение экономии](./keda-finops.md)** — пилот и замер эффекта
* **[KEDA: Тестирование и валидация](./keda-testing-validation.md)** — проверка масштабирования, chaos
* **[KEDA: Вопросы для собеседования](./keda-interview-questions.md)** — систематизация вопросов
* **[Horizontal Pod Autoscaler (HPA): Практические сценарии](../HPA/hpa_scenarios.md)** — стандартное масштабирование
