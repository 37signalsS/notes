# KEDA: Тестирование и валидация масштабирования

## Определения

**Валидация масштабирования** — процесс проверки корректности работы KEDA ScaledObject перед production-развёртыванием: подтверждение что масштабирование вверх/вниз происходит при правильных условиях, cold start укладывается в SLA, fallback работает при сбоях.

**Chaos-тестирование KEDA** — проверка устойчивости автоскейлинга при инъекции сбоев: недоступность источника метрик, падение Kafka/RabbitMQ, network partitions, OOM воркеров.

**Cold Start Validation** — замер времени от появления первого события до готовности первого пода обрабатывать нагрузку. Ключевая метрика для решений о `minReplicaCount: 0` vs `minReplicaCount: 1`.

## Теоретический блок

### Этапы валидации

```text
1. Functional Testing (базовая работоспособность)
   └── Масштабирование вверх при нагрузке
   └── Масштабирование вниз при отсутствии нагрузки
   └── Scale-to-zero и обратно

2. Performance Testing (производительность)
   └── Cold start time (p50, p95, p99)
   └── Time to scale (время от события до пода)
   └── Throughput при разных количествах реплик

3. Resilience Testing (устойчивость)
   └── Fallback при недоступности источника метрик
   └── Поведение при OOM воркеров
   └── Восстановление после restart KEDA Operator

4. Chaos Testing (хаос-инженерия)
   └── Network partition между KEDA и источником метрик
   └── Падение Kafka/RabbitMQ/Redis
   └── Падение Prometheus (при использовании Prometheus scaler)
   └── Исчерпание ResourceQuota

5. Regression Testing (регрессия)
   └── После обновления KEDA версии
   └── После обновления приложения
   └── После изменения конфигурации триггера
```

## Практические сценарии

### Тест 1: Базовое масштабирование вверх/вниз

**Цель:** убедиться что ScaledObject реагирует на нагрузку.

```bash
# Шаг 1: Применить ScaledObject с minReplicaCount: 0
kubectl apply -f scaledobject-test.yaml

# Шаг 2: Проверить что реплик 0
kubectl get scaledobject test-scaler -n app -o jsonpath='{.status.currentReplicaCount}'
# → 0

# Шаг 3: Сгенерировать нагрузку (пример для RabbitMQ)
kubectl run -it --rm loadgen --image=python:3.11 --restart=Never -- bash -c '
pip install pika &&
python3 -c "
import pika, json, time
conn = pika.BlockingConnection(pika.ConnectionParameters(host=\"rabbitmq.app.svc\"))
ch = conn.channel()
ch.queue_declare(queue=\"test-queue\", durable=True)
for i in range(100):
    ch.basic_publish(exchange=\"\", routing_key=\"test-queue\", body=json.dumps({\"id\": i}))
    time.sleep(0.1)
print(\"Published 100 messages\")
"
'

# Шаг 4: Наблюдать за масштабированием
kubectl get hpa -n app -w
# Или
kubectl get scaledobject test-scaler -n app -o jsonpath='{.status.currentReplicaCount}' -w

# Шаг 5: Дождаться обработки всех сообщений
# Шаг 6: Проверить что реплики уменьшаются
kubectl get scaledobject test-scaler -n app -o jsonpath='{.status.currentReplicaCount}' -w
# → 0 (после cooldownPeriod)
```

### Тест 2: Cold Start Validation

**Цель:** замерить время холодного старта.

```bash
# Шаг 1: Убедиться что реплик 0
kubectl scale deployment/test-worker --replicas=0 -n app
kubectl delete scaledobject test-scaler -n app  # убрать KEDA на время замера

# Шаг 2: Засечь время и запустить нагрузку
START=$(date +%s%N)
kubectl run -it --rm loadgen --image=python:3.11 --restart=Never -- bash -c '
pip install pika &&
python3 -c "
import pika, json
conn = pika.BlockingConnection(pika.ConnectionParameters(host=\"rabbitmq.app.svc\"))
ch = conn.channel()
ch.basic_publish(exchange=\"\", routing_key=\"test-queue\", body=json.dumps({\"id\": 999}))
print(\"Message published\")
"
'

# Шаг 3: Ждать пока под станет Ready
kubectl wait --for=condition=ready pod -l app=test-worker -n app --timeout=120s

# Шаг 4: Замерить время
END=$(date +%s%N)
echo "Cold start: $(( ($END - $START) / 1000000 )) ms"
# → Cold start: 12000 ms (12 секунд)

# Шаг 5: Восстановить KEDA
kubectl apply -f scaledobject-test.yaml
```

**Автоматический замер через Prometheus:**

```promql
# Время от создания пода до готовности
kube_pod_status_ready_time{namespace="app", pod=~"test-worker.*"}
- kube_pod_created{namespace="app", pod=~"test-worker.*"}

# Cold start p95 за неделю
histogram_quantile(0.95,
  rate(kube_pod_status_ready_time_bucket{namespace="app"}[7d])
  - rate(kube_pod_created_bucket{namespace="app"}[7d])
)
```

### Тест 3: Fallback при недоступности источника метрик

**Цель:** убедиться что fallback работает и workload не падает.

```bash
# Шаг 1: Убедиться что fallback настроен в ScaledObject
kubectl get scaledobject test-scaler -n app -o jsonpath='{.spec.fallback}'
# → {"failureThreshold":3,"replicas":3,"behavior":"static"}

# Шаг 2: Инжектить ошибку (заблокировать доступ к источнику)
kubectl apply -f - <<EOF
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: block-rabbitmq-from-keda
  namespace: keda
spec:
  podSelector:
    matchLabels:
      app: keda-operator
  policyTypes:
    - Egress
  egress: []  # Блокируем весь egress
EOF

# Шаг 3: Ждать failureThreshold × pollingInterval
# (3 ошибки × 15 сек = 45 сек)

# Шаг 4: Проверить что fallback сработал
kubectl get scaledobject test-scaler -n app -o jsonpath='{.status.conditions}' | jq .
# → FallbackActive: True
kubectl get deployment test-worker -n app -o jsonpath='{.spec.replicas}'
# → 3 (fallback.replicas)

# Шаг 5: Восстановить сетевую политику
kubectl delete networkpolicy block-rabbitmq-from-keda -n keda

# Шаг 6: Проверить возврат к нормальному режиму
kubectl get scaledobject test-scaler -n app -o jsonpath='{.status.conditions}' | jq .
# → FallbackActive: False
```

### Тест 4: Падение Kafka/RabbitMQ

**Цель:** проверить поведение при полной недоступности брокера.

```bash
# Симуляция: scale rabbitmq до 0
kubectl scale statefulset/rabbitmq --replicas=0 -n messaging

# Мониторинг:
# 1. keda_scaler_errors_total должен начать расти
# 2. Алерт KEDAScalerErrors должен сработать
# 3. Fallback должен активироваться
# 4. После восстановленияabbitmq — возврат к норме

# Восстановление:
kubectl scale statefulset/rabbitmq --replicas=3 -n messaging
```

### Тест 5: ResourceQuota exhaustion

**Цель:** проверить что KEDA не создаёт поды сверх квоты.

```bash
# Шаг 1: Установить жёсткую квоту
kubectl apply -f - <<EOF
apiVersion: v1
kind: ResourceQuota
metadata:
  name: test-quota
  namespace: app
spec:
  hard:
    pods: "5"
EOF

# Шаг 2: Создать ScaledObject с maxReplicaCount: 20
kubectl apply -f scaledobject-high-max.yaml

# Шаг 3: Сгенерировать нагрузку (очередь > 1000)
# Шаг 4: Проверить что поды создаются только до квоты
kubectl get pods -n app
# → max 5 подов (вместо 20)

# Шаг 5: Проверить что KEDA НЕ падает при ошибке quota
kubectl get pods -n keda
# → keda-operator в Running (не CrashLoopBackOff)

# Шаг 6: Удалить квоту
kubectl delete resourcequota test-quota -n app
```

### Тест 6: Chaos-тестирование через Chaos Mesh

**Цель:** проверить устойчивость при network partitions.

```yaml
# Сетевой partition между KEDA и Prometheus
apiVersion: chaos-mesh.org/v1alpha1
kind: NetworkChaos
metadata:
  name: keda-prometheus-partition
  namespace: chaos
spec:
  action: partition
  mode: all
  selector:
    labelSelectors:
      app: keda-operator
  direction: both
  target:
    selector:
      labelSelectors:
        app: prometheus
    mode: all
  duration: "5m"
---
# Остановка Kafka Broker
apiVersion: chaos-mesh.org/v1alpha1
kind: PodChaos
metadata:
  name: kill-kafka-broker
  namespace: chaos
spec:
  action: pod-kill
  mode: one
  selector:
    labelSelectors:
      app: kafka
  scheduler:
    cron: "@every 2m"
    duration: "10m"
```

**Валидация результатов:**
- KEDA должен переключиться в fallback
- Поды workload должны оставаться доступными
- После восстановления — нормальное масштабирование
- Метрики `keda_scaler_errors_total` должны показать ошибки во время chaos

### Тест 7: Проверка PDB при scale-down

**Цель:** убедиться что PDB защищает доступность при агрессивном scale-down.

```yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: worker-pdb
  namespace: app
spec:
  minAvailable: 2  # Как минимум 2 пода всегда доступны
  selector:
    matchLabels:
      app: worker
---
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: test-pdb-scaler
  namespace: app
spec:
  scaleTargetRef:
    name: worker
  minReplicaCount: 0
  maxReplicaCount: 10
  triggers:
    - type: rabbitmq
      metadata:
        host: amqp://rabbitmq:5672/
        queueName: tasks
        queueLength: "5"
```

```bash
# Шаг 1: Поднять 5 реплик
# Шаг 2: Удалить очередь (нагрузка = 0)
# Шаг 3: Наблюдать за scale-down
# Шаг 4: Проверить что PDB не нарушен (minAvailable: 2)
kubectl get pdb -n app
# → CURRENT: 2, DESIRED: 2, ALLOWED DISRUPTIONS: 0
```

## Дополнительная информация

### Чек-лист перед production

```text
Functional:
  □ ScaledObject масштабирует вверх при нагрузке
  □ ScaledObject масштабирует вниз при отсутствии нагрузки
  □ Scale-to-zero работает (если minReplicaCount: 0)
  □ Multiple triggers работают корректно (MAX логика)

Cold Start:
  □ Cold start time замерен и < SLA threshold
  □ readiness probe настроен и не блокирует трафик
  □ Docker image оптимизирован (multi-stage build)

Resilience:
  □ Fallback настроен и протестирован
  □ Алерт на KEDAScalerErrors работает
  □ KEDA Operator восстанавливается после restart

Security:
  □ Credentials хранятся в Secret/TriggerAuthentication
  □ NetworkPolicy разрешает доступ KEDA к источнику метрик
  □ RBAC настроен минимально необходимыми правами

Performance:
  □ pollingInterval адекватен (не нагружает источник)
  □ maxReplicaCount учитывает лимиты downstream
  □ PDB настроен для защиты availability
  □ ResourceQuota не блокирует масштабирование

GitOps:
  □ ScaledObject деплоится через ArgoCD/Flux
  □ ignoreDifferences настроен для spec.replicas
  □ Порядок деплоя: ScaledObject -> Deployment
```

### Связь с другими инструментами

- **k6 / Locust:** генерация нагрузки для тестирования HTTP-based скейлеров
- **Chaos Mesh / Litmus:** chaos-тестирование KEDA resilience
- **Prometheus + Grafana:** мониторинг во время тестов
- **SLO monitoring:** валидация что SLA не нарушен во время масштабирования

### См. также

* [KEDA: Основные концепции](./keda_concepts.md) — lifecycle и fallback
* [KEDA: Эксплуатация](./keda-operations.md) — мониторинг и алерты
* [Chaos Engineering](../../../../Chaos_Engineering/chaos_engineering_overview.md) —混沌测试
* [k6 Load Testing](../../../../Testing/k6_load_testing.md) — нагрузочное тестирование
* [PDB](../pod_disruption_budget.md) — защита доступности
