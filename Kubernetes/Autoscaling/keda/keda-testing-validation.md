# KEDA: Тестирование и валидация масштабирования

**Актуально для:** KEDA 2.19.x / 2.20.x, Kubernetes 1.28–1.32+

## Определения

**Валидация масштабирования (Scaling Validation)** — процесс инструментальной проверки корректности работы контроллера KEDA и объектов `ScaledObject`/`ScaledJob` перед переносом в production: подтверждение условий масштабирования вверх и вниз, соблюдение SLA на холодный старт, активация fallback-политик и отсутствие взаимных блокировок с подсистемами Kubernetes.

**Cold Start Validation** — измерение суммарного интервала времени от момента появления первого триггерного события (сообщения в очереди, задачи в брокере) до перехода первого созданного пода рабочей нагрузки в состояние `Ready` и начала обработки трафика. Служит определяющим критерием выбора между `minReplicaCount: 0` (scale-to-zero) и `minReplicaCount: 1`.

**Fallback Verification** — верификация аварийного удержания емкости воркеров. Контролируемый тест поведения системы при недоступности внешнего источника метрик: подтверждает, что при сбое опроса воркеры фиксируются на безопасном количестве реплик, а не сбрасываются в ноль.

**Chaos-тестирование KEDA** — контролируемое внедрение инфраструктурных сбоев (сетевые разрывы, отказ брокера, деградация хранилища, аварийное завершение процесса KEDA Operator, исчерпание лимитов `ResourceQuota`) для проверки отказоустойчивости контура автоскейлинга.

**Flapping / Oscillation Detection** — выявление эффекта паразитной осцилляции (частого переключения реплик вверх-вниз за короткий промежуток времени), вызванного несогласованностью `pollingInterval`, `cooldownPeriod` и настроек HPA `behavior.scaleDown.stabilizationWindowSeconds`.

**Synthetic Smoke Test** — воспроизводимый тест с контролируемой генерацией нагрузки, выполняемый в изолированном тестовом контуре или pre-production кластере для подтверждения сквозного цикла автоскейлинга `0 → N → 0`.

**Contract & Policy Validation** — статический анализ манифестов `ScaledObject` и `TriggerAuthentication` в CI/CD пайплайне на соответствие схемам CRD и корпоративным политикам безопасности (Kyverno, OPA Gatekeeper, Kubeconform).

---

## Базовые концепции и архитектура тестирования

### Пирамида валидации автомасштабирования KEDA

Комплексная проверка автоскейлинга KEDA в инфраструктуре SRE/DevOps строится по многоуровневой схеме:

```text
┌────────────────────────────────────────────────────────┐
│               5. Production Readiness Gate             │
│        (PDB, Graceful Shutdown, Drain, Quota limits)   │
├────────────────────────────────────────────────────────┤
│               4. Resilience & Chaos Testing            │
│         (Fallback, Broker Outage, Operator Failover)   │
├────────────────────────────────────────────────────────┤
│               3. Latency & Cold Start SLA              │
│       (Event-to-Pod Ready, Image Pull, Init delays)    │
├────────────────────────────────────────────────────────┤
│               2. Functional & Dynamic Scaling          │
│       (Scale Up, Scale Down, Scale-to-Zero, Max limits)│
├────────────────────────────────────────────────────────┤
│               1. Static & Schema Validation            │
│      (Kubeconform, CRD Check, Kyverno/OPA, Linter)     │
└────────────────────────────────────────────────────────┘
```

1. **Static & Schema Validation:** проверка манифестов на этапе GitOps/CI без развертывания в кластер (соответствие CRD OpenAPI v3, отсутствие заниженных `pollingInterval < 5`, наличие блока `fallback`).
2. **Functional & Dynamic Scaling:** проверка реакции на появление сообщений в очереди (RabbitMQ/Kafka) или рост запросов к HTTP/Prometheus. Подтверждение расчёта целевого числа реплик:
   $$\text{TargetReplicas} = \left\lceil \frac{\text{CurrentMetricValue}}{\text{TargetValue}} \right\rceil$$
3. **Latency & Cold Start SLA:** фиксация времени реакции контура KEDA (`pollingInterval` + создание пода + запуск контейнера + прохождение `readinessProbe`).
4. **Resilience & Chaos Testing:** проверка поведения при сетевой изоляции брокера, аварийном падении активного пода `keda-operator` (передача лидерства через Kubernetes Lease), таймаутах запросов к экспортерам.
5. **Production Readiness:** валидация совместимости со смежными механизмами кластера: защита от сбоев через `PodDisruptionBudget` (PDB), корректное завершение обработки in-flight задач через `terminationGracePeriodSeconds` при scale-down.

### Поток передачи метрик и критические точки отказа при тестах

```text
[Источник метрик: RabbitMQ / Kafka / Prometheus]
           │
           │ (1) Опрос скейлером (каждые pollingInterval сек)
           ▼
[keda-operator] ─────────► [Kubernetes API Server: HPA Controller]
           │                                 ▲
           │ (2) Регистрация/обновление HPA │ (3) Запрос внешних метрик
           ▼                                 │     (каждые 15 сек)
[keda-operator-metrics-apiserver] ───────────┘
           │
           ▼
[Workload: Deployment / StatefulSet] ◄─── Изменение spec.replicas
```

* **Точка отказа 1 (Источник → Operator):** Сетевые ошибки, неверные учетные данные (`TriggerAuthentication`), отказ брокера. Проверяется тестами Fallback и Network Chaos.
* **Точка отказа 2 (Operator → APIServer):** Ошибки RBAC, конфликты версий CRD, зависание лидера. Проверяется тестами failover оператора.
* **Точка отказа 3 (Metrics Server → HPA):** Таймауты агрегированного API-сервера, задержка синхронизации HPA. Проверяется проверкой статуса HPA (`AbleToScale`, `ScalingActive`).
* **Точка отказа 4 (Workload Scale):** Недостаток ресурсов узлов, исчерпание `ResourceQuota`, блокировка со стороны PDB. Проверяется тестами граничных условий.

### Ключевые метрики Prometheus для валидации KEDA

Во время проведения нагрузочных и хаос-тестов SRE отслеживает следующие метрики:

| Метрика Prometheus | Тип | Описание при валидации |
|---|---|---|
| `keda_scaler_errors_total` | Counter | Количество ошибок опроса источника метрик. В нормальном тесте должно быть равно 0. При chaos-тесте должно расти. |
| `keda_scaledobject_fallback_activity` | Gauge | `1` — объект переведен в аварийный режим Fallback; `0` — штатная работа. |
| `keda_scaler_active` | Gauge | `1` — скейлер зафиксировал нагрузку выше порога активации (выход из 0); `0` — нагрузка отсутствует. |
| `keda_scaler_metrics_value` | Gauge | Текущее значение метрики, прочитанное скейлером KEDA из источника. |
| `kube_pod_status_ready_time` | Gauge | Временная метка перехода пода рабочей нагрузки в состояние `Ready`. |

---

## Практические сценарии

### Сценарий 1: Статическая валидация манифестов ScaledObject в CI/CD

**Цель:** перехватить синтаксические ошибки, несоответствие CRD и нарушения политик надежности до выката манифестов в кластер.

#### 1. Проверка схемы через Kubeconform

Для валидации пользовательских ресурсов KEDA в CI/CD без прямого подключения к кластеру используются схемы OpenAPI:

```bash
# Шаг 1: Валидация манифеста через kubeconform с загрузкой CRD схем KEDA
kubeconform \
  -schema-location default \
  -schema-location 'https://raw.githubusercontent.com/datreeio/CRDs-catalog/main/{{.Group}}/{{.ResourceKind}}_{{.ResourceAPIVersion}}.json' \
  -summary \
  -strict \
  scaledobject.yaml
# → scaledobject.yaml - ScaledObject test-consumer-scaler is valid
```

#### 2. Проверка политик надежности через Kyverno CLI

Создадим правило валидации, гарантирующее наличие секции `fallback` и безопасный `pollingInterval` во всех `ScaledObject`:

```yaml
# policy-keda-rules.yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: require-keda-resilience
spec:
  validationFailureAction: Enforce
  rules:
    - name: check-fallback-and-interval
      match:
        any:
          - resources:
              kinds:
                - ScaledObject
      validate:
        message: "ScaledObject обязан содержать секцию fallback и pollingInterval >= 5"
        pattern:
          spec:
            pollingInterval: ">4"
            fallback:
              failureThreshold: ">0"
              replicas: ">0"
```

Выполнение проверки в CI пайплайне:

```bash
kyverno apply policy-keda-rules.yaml --resource scaledobject.yaml
# → Applying 1 policy rule to 1 resource...
# → (statistic: passes: 1, fails: 0, errors: 0, warns: 0)
```

---

### Сценарий 2: Функциональное тестирование полного цикла масштабирования (0 → N → 0)

**Цель:** подтвердить реакцию `ScaledObject` на появление сообщений, корректный расчет реплик и возврат в 0 по истечении `cooldownPeriod`.

#### 1. Развертывание тестового окружения

```yaml
# test-rabbitmq-workload.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: rabbitmq-consumer
  namespace: test-scaling
spec:
  replicas: 0
  selector:
    matchLabels:
      app: rabbitmq-consumer
  template:
    metadata:
      labels:
        app: rabbitmq-consumer
    spec:
      containers:
        - name: consumer
          image: alpine:3.20
          command: ["/bin/sh", "-c"]
          args:
            - |
              trap 'echo "Terminating gracefully..."; exit 0' SIGTERM SIGINT
              while true; do sleep 1; done
          resources:
            requests:
              cpu: 50m
              memory: 64Mi
            limits:
              cpu: 100m
              memory: 128Mi
---
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: rabbitmq-consumer-scaler
  namespace: test-scaling
spec:
  scaleTargetRef:
    name: rabbitmq-consumer
  minReplicaCount: 0
  maxReplicaCount: 10
  pollingInterval: 10
  cooldownPeriod: 30
  triggers:
    - type: rabbitmq
      metadata:
        protocol: amqp
        host: amqp://guest:guest@rabbitmq.middleware.svc.cluster.local:5672/
        queueName: validation-queue
        mode: QueueLength
        value: "10"
```

Применение манифеста и проверка исходного состояния:

```bash
kubectl apply -f test-rabbitmq-workload.yaml
# → deployment.apps/rabbitmq-consumer created
# → scaledobject.keda.sh/rabbitmq-consumer-scaler created

# Проверка исходного статуса (реплик должно быть 0)
kubectl get scaledobject rabbitmq-consumer-scaler -n test-scaling
# → NAME                       SCALETARGETKIND   SCALETARGETNAME     MIN   MAX   TRIGGERS   AUTHENTICATION   READY   ACTIVE   FALLBACK   AGE
# → rabbitmq-consumer-scaler   Deployment        rabbitmq-consumer   0     10    rabbitmq                    True    False    False      15s
```

#### 2. Генерация тестовой нагрузки

Генерируем 50 сообщений в тестовую очередь:

```bash
kubectl run -i --rm rabbitmq-producer --image=curlimages/curl:8.10.1 --restart=Never -n test-scaling -- sh -c '
for i in $(seq 1 50); do
  curl -s -u guest:guest -X POST "http://rabbitmq.middleware.svc.cluster.local:15672/api/exchanges/%2F/amq.default/publish" \
    -H "Content-Type: application/json" \
    -d "{\"properties\":{},\"routing_key\":\"validation-queue\",\"payload\":\"msg-$i\",\"payload_encoding\":\"string\"}" > /dev/null
done
echo "Published 50 messages"
'
# → Published 50 messages
```

#### 3. Валидация перехода масштабирования

```bash
# Мониторинг статуса ScaledObject:
kubectl get scaledobject rabbitmq-consumer-scaler -n test-scaling -w
# → NAME                       SCALETARGETKIND   SCALETARGETNAME     MIN   MAX   TRIGGERS   READY   ACTIVE   FALLBACK   AGE
# → rabbitmq-consumer-scaler   Deployment        rabbitmq-consumer   0     10    rabbitmq   True    True     False      45s

# Проверка рассчитанного количества реплик (50 сообщений / value: 10 = 5 реплик)
kubectl get deployment rabbitmq-consumer -n test-scaling
# → NAME                READY   UP-TO-DATE   AVAILABLE   AGE
# → rabbitmq-consumer   5/5     5            5           2m

# Очистка очереди через RabbitMQ API для имитации завершения обработки
kubectl run -i --rm rabbitmq-purge --image=curlimages/curl:8.10.1 --restart=Never -n test-scaling -- \
  curl -s -u guest:guest -X DELETE "http://rabbitmq.middleware.svc.cluster.local:15672/api/queues/%2F/validation-queue/contents"
# → {"message":"cleared"}

# Ожидание истечения cooldownPeriod (30 сек) и проверка возврата в 0:
sleep 40
kubectl get deployment rabbitmq-consumer -n test-scaling
# → NAME                READY   UP-TO-DATE   AVAILABLE   AGE
# → rabbitmq-consumer   0/0     0            0           4m
```

---

### Сценарий 3: Замер и валидация времени холодного старта (Cold Start SLA)

**Цель:** измерить реальное время от момента появления нагрузки до готовности первого пода обрабатывать задачи (`Ready: True`) для верификации соответствия SLA.

#### 1. Автоматизированный замер через CLI-скрипт

```bash
# Предварительно убеждаемся, что подов 0
kubectl scale deployment/rabbitmq-consumer --replicas=0 -n test-scaling
# → deployment.apps/rabbitmq-consumer scaled

# Запуск мониторинга и публикация одного тестового сообщения
START_TS=$(date +%s%3N)
echo "Start time: $START_TS ms"

# Публикация сообщения-триггера
kubectl run -i --rm trigger-producer --image=curlimages/curl:8.10.1 --restart=Never -n test-scaling -- \
  curl -s -u guest:guest -X POST "http://rabbitmq.middleware.svc.cluster.local:15672/api/exchanges/%2F/amq.default/publish" \
    -H "Content-Type: application/json" \
    -d '{"properties":{},"routing_key":"validation-queue","payload":"trigger","payload_encoding":"string"}' > /dev/null

# Ожидание появления и перехода первого пода в Ready
kubectl wait --for=condition=ready pod -l app=rabbitmq-consumer -n test-scaling --timeout=90s
# → pod/rabbitmq-consumer-7d8b598b9-x2b4c condition met

END_TS=$(date +%s%3N)
DURATION=$((END_TS - START_TS))
echo "Cold start total duration: ${DURATION} ms ($(( DURATION / 1000 )) s)"
# → Cold start total duration: 12450 ms (12 s)
```

#### 2. Замер распределения Cold Start через Prometheus (PromQL)

В production-средах ручной замер заменяется непрерывным мониторингом перцентилей времени готовности подов:

```promql
# Точечный расчет времени старта для каждого пода (в секундах)
(kube_pod_status_ready_time{namespace="test-scaling", pod=~"rabbitmq-consumer-.*"} 
 - kube_pod_created{namespace="test-scaling", pod=~"rabbitmq-consumer-.*"})

# Анализ квантиля p95 задержки холодного старта за последние сутки:
histogram_quantile(0.95,
  sum by (le) (
    rate(kube_pod_status_ready_time_bucket{namespace="test-scaling"}[1d])
  )
)
```

---

### Сценарий 4: Верификация аварийного режима Fallback при изоляции источника метрик

**Цель:** подтвердить, что при сетевой изоляции брокера KEDA не сбрасывает воркеры в 0, а переводит нагрузку на заданное количество fallback-реплик.

#### 1. Настройка ScaledObject с конфигурацией Fallback

```yaml
# scaledobject-fallback-test.yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: fallback-scaler
  namespace: test-scaling
spec:
  scaleTargetRef:
    name: rabbitmq-consumer
  minReplicaCount: 0
  maxReplicaCount: 10
  pollingInterval: 10
  fallback:
    failureThreshold: 3
    replicas: 4
    behavior: static
  triggers:
    - type: rabbitmq
      metadata:
        protocol: amqp
        host: amqp://guest:guest@rabbitmq.middleware.svc.cluster.local:5672/
        queueName: validation-queue
        value: "10"
```

Применяем конфигурацию:

```bash
kubectl apply -f scaledobject-fallback-test.yaml
# → scaledobject.keda.sh/fallback-scaler configured
```

#### 2. Инъекция сетевой изоляции через NetworkPolicy

Блокируем доступ от подов `keda-operator` к RabbitMQ в пространстве `middleware`:

```yaml
# isolate-keda-networkpolicy.yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: isolate-rabbitmq-from-keda
  namespace: middleware
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: rabbitmq
  policyTypes:
    - Ingress
  ingress:
    - from:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: test-scaling # Разрешаем доступ только воркерам, блокируя keda
```

```bash
kubectl apply -f isolate-keda-networkpolicy.yaml
# → networkpolicy.networking.k8s.io/isolate-rabbitmq-from-keda created
```

#### 3. Валидация срабатывания Fallback

Расчётное время перехода: $\text{failureThreshold} \times \text{pollingInterval} = 3 \times 10 = 30\text{ секунд}$.

```bash
# Ожидание 35 секунд
sleep 35

# Проверка условий ScaledObject
kubectl get scaledobject fallback-scaler -n test-scaling -o jsonpath='{range .status.conditions[*]}{.type}{"\t"}{.status}{"\t"}{.reason}{"\t"}{.message}{"\n"}{end}'
# → Ready       True    ScaledObjectReady       ScaledObject is ready for scaling
# → Active      False   ScalerMetricsError      error getting metrics from rabbitmq
# → Fallback    True    FallbackActive          Scaler error count exceeded threshold, fallback active

# Проверка фактического числа реплик воркера (должно быть 4)
kubectl get deployment rabbitmq-consumer -n test-scaling -o jsonpath='{.spec.replicas}'
# → 4

# Проверка метрик в Prometheus
curl -s "http://prometheus-k8s.monitoring.svc:9090/api/v1/query?query=keda_scaledobject_fallback_activity%7BscaledObject%3D%22fallback-scaler%22%7D" | jq -r '.data.result[0].value[1]'
# → 1
```

#### 4. Восстановление и проверка выхода из Fallback

```bash
kubectl delete networkpolicy isolate-rabbitmq-from-keda -n middleware
# → networkpolicy.networking.k8s.io "isolate-rabbitmq-from-keda" deleted

# Ожидание одного интервала опроса
sleep 15

kubectl get scaledobject fallback-scaler -n test-scaling -o jsonpath='{range .status.conditions[?(@.type=="Fallback")]}{.status}{"\t"}{.reason}{"\n"}{end}'
# → False   NoFallbackOccurred
```

---

### Сценарий 5: Инъекция сбоев в брокер очередей (On-Premises Kafka/RabbitMQ)

**Цель:** верифицировать поведение оператора KEDA при внезапном падении брокера (Connection Refused / TCP Timeout).

#### 1. Симуляция падения брокера

```bash
# Остановка подов StatefulSet брокера RabbitMQ
kubectl scale statefulset rabbitmq -n middleware --replicas=0
# → statefulset.apps/rabbitmq scaled

# Проверка логов оператора KEDA на перехват ошибок подключения
kubectl logs -n keda -l app.kubernetes.io/name=keda-operator --tail=50 | grep -i "error"
# → 2026-10-13T15:40:12Z ERROR controllers.ScaledObject Error getting scale decision {"ScaledObject.Namespace": "test-scaling", "ScaledObject.Name": "fallback-scaler", "error": "dial tcp: lookup rabbitmq.middleware.svc.cluster.local: connection refused"}

# Проверка роста счетчика ошибок в Prometheus
curl -s "http://prometheus-k8s.monitoring.svc:9090/api/v1/query?query=increase(keda_scaler_errors_total%5B2m%5D)" | jq -r '.data.result[0].value[1]'
# → 12.0
```

#### 2. Восстановление брокера

```bash
kubectl scale statefulset rabbitmq -n middleware --replicas=3
# → statefulset.apps/rabbitmq scaled

kubectl rollout status statefulset/rabbitmq -n middleware
# → statefulset rolling update complete 3 pods at revision rabbitmq-7f8d689b...

# Проверка стабилизации оператора
kubectl get scaledobject fallback-scaler -n test-scaling -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}'
# → True
```

---

### Сценарий 6: Тестирование граничных условий ResourceQuota и LimitRange

**Цель:** убедиться, что исчерпание лимитов `ResourceQuota` в целевом namespace не приводит к краху KEDA Operator или бесконечной рассинхронизации статусов.

#### 1. Установка жесткой квоты

```yaml
# test-quota.yaml
apiVersion: v1
kind: ResourceQuota
metadata:
  name: strict-pod-quota
  namespace: test-scaling
spec:
  hard:
    pods: "3"
    requests.cpu: "200m"
    requests.memory: "256Mi"
```

```bash
kubectl apply -f test-quota.yaml
# → resourcequota/strict-pod-quota created
```

#### 2. Подача нагрузки с требованием масштабирования до 10 реплик

Публикуем 100 сообщений в очередь:

```bash
kubectl run -i --rm bulk-producer --image=curlimages/curl:8.10.1 --restart=Never -n test-scaling -- sh -c '
for i in $(seq 1 100); do
  curl -s -u guest:guest -X POST "http://rabbitmq.middleware.svc.cluster.local:15672/api/exchanges/%2F/amq.default/publish" \
    -H "Content-Type: application/json" \
    -d "{\"properties\":{},\"routing_key\":\"validation-queue\",\"payload\":\"bulk-$i\",\"payload_encoding\":\"string\"}" > /dev/null
done
'
```

#### 3. Анализ поведения HPA и событий Deployment

```bash
# Проверка желаемого числа реплик в Deployment vs реально созданные
kubectl get deployment rabbitmq-consumer -n test-scaling
# → NAME                READY   UP-TO-DATE   AVAILABLE   AGE
# → rabbitmq-consumer   3/10    3            3           12m

# Проверка событий ReplicaSet (ошибки исчерпания квоты)
kubectl get events -n test-scaling --field-selector reason=FailedCreate --sort-by='.metadata.creationTimestamp' | tail -n 3
# → 25s   Warning   FailedCreate   replicaset/rabbitmq-consumer-7d8b598b9   Error creating: pods "rabbitmq-consumer-7d8b598b9-k8z5t" is forbidden: exceeded quota: strict-pod-quota, requested: pods=1, used: pods=3, limited: pods=3

# Проверка статуса KEDA Operator: оператор должен продолжать функционировать
kubectl get pods -n keda -l app.kubernetes.io/name=keda-operator
# → NAME                             READY   STATUS    RESTARTS   AGE
# → keda-operator-586b6bc494-b4x7l   1/1     Running   0          4d

# Удаление квоты и проверка расширения до 10 реплик
kubectl delete resourcequota strict-pod-quota -n test-scaling
# → resourcequota "strict-pod-quota" deleted

kubectl rollout status deployment/rabbitmq-consumer -n test-scaling --timeout=60s
# → deployment "rabbitmq-consumer" successfully rolled out
```

---

### Сценарий 7: Chaos-тестирование через Chaos Mesh (Network Partition и failover KEDA Operator)

**Цель:** проверить отказоустойчивость контура масштабирования при разрыве сетевых связей и аварийном падении активной реплики оператора.

#### 1. Сетевая изоляция KEDA Operator от Prometheus

```yaml
# chaos-network-partition.yaml
apiVersion: chaos-mesh.org/v1alpha1
kind: NetworkChaos
metadata:
  name: partition-keda-prometheus
  namespace: chaos-testing
spec:
  action: partition
  mode: all
  selector:
    namespaces:
      - keda
    labelSelectors:
      app.kubernetes.io/name: keda-operator
  direction: both
  target:
    selector:
      namespaces:
        - monitoring
      labelSelectors:
        app.kubernetes.io/name: prometheus
    mode: all
  duration: "3m"
```

Применение хаос-эксперимента:

```bash
kubectl apply -f chaos-network-partition.yaml
# → networkchaos.chaos-mesh.org/partition-keda-prometheus created

# Проверка статуса эксперимента
kubectl get networkchaos partition-keda-prometheus -n chaos-testing -o jsonpath='{.status.experiment.phase}'
# → Running
```

#### 2. Проверка HA и Leader Election оператора KEDA при аварии

В High-Availability инсталляции KEDA работают 2+ реплики с координацией через Kubernetes Lease:

```bash
# Проверка текущего лидера
kubectl get lease keda-operator-leader -n keda -o jsonpath='{.spec.holderIdentity}'
# → keda-operator-586b6bc494-b4x7l

# Принудительное уничтожение пода активного лидера
CURRENT_LEADER=$(kubectl get lease keda-operator-leader -n keda -o jsonpath='{.spec.holderIdentity}')
kubectl delete pod "$CURRENT_LEADER" -n keda --now
# → pod "keda-operator-586b6bc494-b4x7l" deleted

# Проверка смены лидера без деградации масштабирования
sleep 5
kubectl get lease keda-operator-leader -n keda -o jsonpath='{.spec.holderIdentity}'
# → keda-operator-586b6bc494-m8z9p

# Проверка: HPA не потерял метрики
kubectl get hpa keda-hpa-rabbitmq-consumer-scaler -n test-scaling
# → NAME                                REFERENCE                      TARGETS          MINPODS   MAXPODS   REPLICAS   AGE
# → keda-hpa-rabbitmq-consumer-scaler   Deployment/rabbitmq-consumer   10/10 (avg)      1         10        5          15m
```

---

### Сценарий 8: Валидация защиты доступности и Graceful Shutdown (PDB + terminationGracePeriodSeconds)

**Цель:** подтвердить, что при внезапном падении очереди до 0 реплик воркеры корректно дообрабатывают принятые сообщения, а PDB защищает от превышения порога недоступности.

#### 1. Опасность конфликта PDB и Scale-to-Zero

Если для сервиса с `minReplicaCount: 0` задан PDB с `minAvailable: 1`, контроллер Eviction заблокирует удаление последнего пода при `kubectl drain` или добровольных выселениях. Однако HPA удаляет реплики напрямую через изменение `spec.replicas`, минуя Eviction API.

Проверим корректное поведение завершения подов воркеров:

```yaml
# worker-graceful-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: graceful-worker
  namespace: test-scaling
spec:
  replicas: 3
  selector:
    matchLabels:
      app: graceful-worker
  template:
    metadata:
      labels:
        app: graceful-worker
    spec:
      terminationGracePeriodSeconds: 45
      containers:
        - name: worker
          image: alpine:3.20
          command: ["/bin/sh", "-c"]
          args:
            - |
              trap 'echo "SIGTERM received. Finishing current task (15s)..."; sleep 15; echo "Task finished. Exiting."; exit 0' SIGTERM
              while true; do sleep 1; done
          lifecycle:
            preStop:
              exec:
                command: ["/bin/sh", "-c", "sleep 5"]
          resources:
            requests:
              cpu: 20m
              memory: 32Mi
```

#### 2. Тестирование сброса реплик в 0

```bash
kubectl apply -f worker-graceful-deployment.yaml
# → deployment.apps/graceful-worker configured

# Имитируем команду масштабирования в ноль
kubectl scale deployment graceful-worker --replicas=0 -n test-scaling
# → deployment.apps/graceful-worker scaled

# Мониторинг логов завершающегося пода
POD_NAME=$(kubectl get pods -n test-scaling -l app=graceful-worker -o jsonpath='{.items[0].metadata.name}')
kubectl logs -f "$POD_NAME" -n test-scaling
# → SIGTERM received. Finishing current task (15s)...
# → Task finished. Exiting.
```

---

### Сценарий 9: Нагрузочное тестирование триггеров метрик через k6 (HTTP / Prometheus Scaler)

**Цель:** провести ступенчатое нагрузочное тестирование HTTP-сервиса, масштабируемого через KEDA Prometheus Scaler, и проверить отсутствие эффекта flapping.

#### 1. Конфигурация ScaledObject со сглаживанием HPA Behavior

```yaml
# http-prometheus-scaler.yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: web-api-scaler
  namespace: test-scaling
spec:
  scaleTargetRef:
    name: web-api
  minReplicaCount: 1
  maxReplicaCount: 20
  pollingInterval: 10
  cooldownPeriod: 60
  advanced:
    horizontalPodAutoscalerConfig:
      behavior:
        scaleDown:
          stabilizationWindowSeconds: 120
          policies:
            - type: Percent
              value: 20
              periodSeconds: 30
        scaleUp:
          stabilizationWindowSeconds: 0
          policies:
            - type: Percent
              value: 100
              periodSeconds: 15
  triggers:
    - type: prometheus
      metadata:
        serverAddress: http://prometheus-k8s.monitoring.svc:9090
        metricName: http_requests_per_second
        query: sum(rate(http_requests_total{namespace="test-scaling", app="web-api"}[1m]))
        threshold: "50"
```

#### 2. Сценарий нагрузочного теста k6

```javascript
// k6-scaling-test.js
import http from 'k6/http';
import { check, sleep } from 'k6';

export const options = {
  stages: [
    { duration: '1m', target: 20 },   // Разогрев (ниже порога скейлинга)
    { duration: '3m', target: 200 },  // Ступенчатый всплеск нагрузки
    { duration: '2m', target: 200 },  // Плато (проверка удержания реплик)
    { duration: '2m', target: 0 },    // Сброс (проверка stabilizationWindow)
  ],
  thresholds: {
    http_req_duration: ['p(95)<300'], // SLA по задержке ответов
    http_req_failed: ['rate<0.01'],   // Ошибок менее 1%
  },
};

export default function () {
  const res = http.get('http://web-api.test-scaling.svc.cluster.local:8080/api/v1/health');
  check(res, { 'status is 200': (r) => r.status === 200 });
  sleep(0.1);
}
```

Запуск нагрузочного теста внутри кластера:

```bash
kubectl run -i --rm k6-runner --image=grafana/k6:0.54.0 --restart=Never -n test-scaling -- \
  run - < k6-scaling-test.js
# →      ✓ status is 200
# →      checks.........................: 100.00% ✓ 48200      ✗ 0
# →      http_req_duration..............: avg=42.1ms min=8.2ms med=28.4ms max=184.2ms p(95)=92.6ms
# →      http_req_failed................: 0.00%   ✓ 0          ✗ 48200
```

Во время прогона теста проверяется график числа реплик: плавное ступенчатое нарастание без осцилляций и ступенчатое снижение с задержкой 120 секунд.

---

## Диагностика и устранение неполадок (Troubleshooting)

| Проблема / Симптом | Вероятная причина | Диагностика | Решение |
|---|---|---|---|
| **Нагрузка подана, но воркеры не масштабируются из нуля (`0 → 1`)** | 1. Ошибка связи с брокером.<br>2. Опечатка в имени очереди/топика.<br>3. Не сработал скейлер (`keda_scaler_active = 0`). | `kubectl describe scaledobject <name>`<br>`kubectl logs -n keda deploy/keda-operator \| grep -i error` | Исправить опечатку в `metadata.queueName`. Проверить `TriggerAuthentication` и сетевую связность до брокера. |
| **Осцилляция (Flapping): поды постоянно масштабируются вверх и вниз** | Отсутствует окно стабилизации HPA (`stabilizationWindowSeconds`), либо `pollingInterval` слишком мал по сравнению со временем обработки задачи. | Проверить историю реплик:<br>`kubectl get hpa -w`<br>Сверить с графиком метрики. | Настроить секцию `advanced.horizontalPodAutoscalerConfig.behavior.scaleDown.stabilizationWindowSeconds: 300` и увеличить `cooldownPeriod`. |
| **HPA показывает `unknown` в колонке `TARGETS`** | `keda-operator-metrics-apiserver` не зарегистрирован или его Service не отвечает. | `kubectl get apiservice v1beta1.external.metrics.k8s.io`<br>`kubectl logs -n keda deploy/keda-metrics-apiserver` | Перезапустить поды `keda-metrics-apiserver`. Проверить валидность TLS-сертификатов агрегированного API-сервера. |
| **Fallback не активируется при отказе источника** | Значение `failureThreshold` слишком велико, либо скейлер возвращает `0` вместо ошибки протокола. | `kubectl get scaledobject <name> -o jsonpath='{.status.conditions}' \| jq .` | Снизить `failureThreshold` до 3. Проверить реализацию триггера и логи оператора. |
| **PDB блокирует `kubectl drain` при `minReplicaCount: 0`** | В PDB задано жесткое правило `minAvailable: 1`, а нагрузка сброшена в ноль. | `kubectl get pdb -A`<br>`kubectl describe pdb <name>` | Использовать процентное соотношение в PDB (`maxUnavailable: 20%`) либо исключать scale-to-zero компоненты из жестких PDB. |
| **Cold Start SLA нарушается (> 60 сек)** | Долгий pull тяжелого контейнера (нет кэша на ноде), долгие `initContainers` или `readinessProbe.initialDelaySeconds`. | `kubectl describe pod <name>` (блок Events)<br>Замерить тайминги фаз старта. | Оптимизировать Dockerfile (multi-stage build), настроить локальный Image Registry Cache, оптимизировать readiness probe. |

### Практическая диагностика зависшего ScaledObject

Комплексная команда для извлечения всех условий и причин сбоя объекта:

```bash
kubectl get scaledobject -A -o jsonpath='{range .items[*]}{.metadata.namespace}{"\t"}{.metadata.name}{"\t"}{range .status.conditions[*]}{.type}={.status} ({.reason}: {.message}){"\t"}{end}{"\n"}{end}'
# → test-scaling   rabbitmq-consumer-scaler   Ready=True (ScaledObjectReady: ScaledObject is ready)   Active=False (NoMetricFound: queue is empty)   Fallback=False (NoFallback: operating normally)
```

---

## Рекомендации и Best Practices

### Архитектурные правила тестирования

1. **Изоляция сред тестирования:** Нагрузочные и хаос-тесты KEDA должны выполняться в выделенном namespace или отдельном staging-кластере. Не допускается проведение chaos-экспериментов с остановкой оператора KEDA в production без ограничения blast radius.
2. **Обязательное включение Fallback для критических сервисов:** Каждый `ScaledObject` критического контура обязан иметь блок `fallback` с `behavior: static` или `currentReplicasIfHigher`, чтобы при отказе системы мониторинга не произошло полного отключения обработчиков.
3. **Согласование таймаутов:**
   * `pollingInterval` должен быть не менее 5 секунд (рекомендуется 10–30 с) во избежание перегрузки источника метрик.
   * `terminationGracePeriodSeconds` воркера обязан превышать максимальное время обработки одного сообщения из очереди.
4. **Валидация PDB:** Для сервисов, поддерживающих scale-to-zero (`minReplicaCount: 0`), запрещено использование `minAvailable: 1` в `PodDisruptionBudget`. Рекомендуется использовать `maxUnavailable: 1` или `maxUnavailable: 33%`.

---

### Чек-лист готовности к Production (Production Readiness Checklist)

```text
Static & Schema:
  [ ] Манифесты валидированы через kubeconform на соответствие CRD KEDA 2.19/2.20.
  [ ] Kyverno/OPA политики проверяют наличие fallback и допустимый pollingInterval (>= 5s).
  [ ] TriggerAuthentication хранит пароли и токены исключительно в Kubernetes Secret.

Functional & Scaling:
  [ ] Проверено масштабирование вверх при росте очереди/метрик.
  [ ] Проверен возврат в minReplicaCount после исчезновения нагрузки.
  [ ] Проверен scale-to-zero (если применим) и выход из нуля при первом сообщении.
  [ ] maxReplicaCount согласован с пропускной способностью нижележащих БД и хранилищ.

Cold Start & Performance:
  [ ] Замерено время холодного старта (p50, p95) и укладывается в утвержденный SLA.
  [ ] Образы воркеров оптимизированы, readinessProbe начинает опрос без задержек.
  [ ] Проверено отсутствие осцилляций (Flapping) при импульсной нагрузке.

Resilience & Chaos:
  [ ] Протестирован режим Fallback при искусственной сетевой изоляции брокера/Prometheus.
  [ ] Протестировано поведение воркеров при падении брокера очередей.
  [ ] Протестирован failover пода keda-operator (передача Kubernetes Lease).
  [ ] Проверено поведение при исчерпании лимитов ResourceQuota.

Operations & Observability:
  [ ] Настроены алерты в Prometheus на keda_scaler_errors_total и переход в Fallback.
  [ ] Воркеры настроены на Graceful Shutdown с обработкой сигнала SIGTERM.
  [ ] PDB не создает взаимных блокировок при масштабировании в ноль.
```

---

## Дополнительная информация

### Взаимодействие с инструментами тестирования

* **k6:** генератор нагрузки для тестирования HTTP-сервисов и экспортеров метрик.
* **Chaos Mesh:** платформа хаос-инженерии для инъекции сетевых разрывов, задержек и аварийных перезапусков подов в Kubernetes.
* **Kubeconform & Kyverno:** инструменты статической валидации схем и соблюдения архитектурных политик в CI/CD.
* **Prometheus:** источник телеметрии для валидации времени старта подов и мониторинга ошибок скейлера KEDA.

### См. также

* [KEDA: Основные концепции](./keda_concepts.md) — архитектура оператора, жизненный цикл и CRD
* [KEDA: Эксплуатация и мониторинг](./keda-operations.md) — метрики, алерты и устранение инцидентов
* [KEDA: FinOps и оптимизация затрат](./keda-finops.md) — расчет эффекта от scale-to-zero и оптимизация ресурсов
* [PodDisruptionBudget](../pod_disruption_budget.md) — защита доступности приложений при добровольных прерываниях
* [Нагрузочное тестирование с помощью k6](../../../Testing/k6_load_testing.md) — методология генерации нагрузки Performance-as-Code
* [Обзор Chaos Engineering](../../../Chaos_Engineering/chaos_engineering_overview.md) — принципы и методология хаос-тестирования
* [Инструменты Chaos Engineering](../../../Chaos_Engineering/chaos_engineering_tools.md) — практическое использование Chaos Mesh и Litmus
