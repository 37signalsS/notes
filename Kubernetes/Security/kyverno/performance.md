# Производительность и масштабирование Kyverno

## Определения

**Webhook Latency** — задержка обработки admission-запроса вебхуком Kyverno. Включает сетевую задержку (RTT), время обработки политики и время ответа API-серверу. Целевое значение для production: <50ms (P95).

**CEL-First Architecture** — подход, при котором базовые проверки валидации передаются в нативный `ValidatingAdmissionPolicy` Kubernetes (GA с v1.30). Работает внутри процесса API-сервера без вызова внешних вебхуков, что снижает задержку на 30–50% по сравнению с классическим webhook.

**GlobalContext** — механизм кэширования данных из внешних источников (API-вызовы, конфигурации) для повторного использования в политиках. Снижает нагрузку на API-сервер и уменьшает задержку при работе с внешними данными.

---

## Основные концепции

### Архитектурные модели и их влияние на задержку

```text
┌─────────────────────────────────────────────────────────────────┐
│  Модель 1: Классический Webhook (v1 ClusterPolicy)             │
│  ────────────────────────────────────────────────────────────  │
│  API-сервер → Network (5-15ms) → Kyverno Webhook → Response   │
│  Средняя задержка: 15-30ms (P95)                               │
│  Ограничение: Leader Election + 1 контроллер                   │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│  Модель 2: CEL-First (v2 ValidatingPolicy)                     │
│  ────────────────────────────────────────────────────────────  │
│  API-сервер → CEL Runtime (внутри процесса) → Response        │
│  Средняя задержка: <1ms (P95)                                   │
│  Ограничение: только валидация (нет мутации/генерации)          │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│  Модель 3: Гибридная (CEL + Webhook)                            │
│  ────────────────────────────────────────────────────────────  │
│  ValidatingPolicy (CEL) → ClusterPolicy (Webhook)              │
│  Использование: базовые проверки через CEL, сложные — через webhook │
└─────────────────────────────────────────────────────────────────┘
```

### Влияние количества политик на задержку

| Количество политик | Модель v1 (Webhook) | Модель v2 (CEL) | Причина |
| :--- | :--- | :--- | :--- |
| 1-10 | 15-30ms | <1ms | Малое количество правил, быстрая компиляция |
| 10-50 | 30-80ms | <1ms | Линейный рост при webhook, константно при CEL |
| 50-100 | 80-200ms | <1ms | Кэширование правил в Kyverno v1, нативность CEL |
| 100+ | 200ms-1s | <2ms | Конвейер webhook, параллельная компиляция CEL |

### Оптимальное распределение ресурсов контроллеров

```yaml
# Рекомендуемые ресурсы для production-кластеров
# Средний кластер (100 нод, 500 подов)
apiVersion: apps/v1
kind: Deployment
metadata:
  name: kyverno-admission-controller
spec:
  replicas: 3  # Leader Election + 2 standby
  template:
    spec:
      containers:
        - name: kyverno
          resources:
            requests:
              cpu: 500m
              memory: 512Mi
            limits:
              cpu: 1000m
              memory: 1Gi
          args:
            - --webhookTimeoutSeconds=30
            - --maxWebhookConcurrent=20

        # Background Controller (отдельный процесс)
        - name: background-controller
          resources:
            requests:
              cpu: 100m
              memory: 256Mi
            limits:
              cpu: 500m
              memory: 512Mi
```

---

## Практические сценарии

### Сценарий 1: Оптимизация webhook-задержки

**Проблема:** P95 задержка API-сервера >200ms после внедрения 50 политик.

**Диагностика:**

```bash
# Измерение текущей задержки
kubectl port-forward -n kyverno svc/kyverno-svc-metrics 8080:8080
curl -s http://localhost:8080/metrics | grep kyverno_admission_review_duration_seconds

# Анализ топ-5 самых медленных политик
kubectl get clusterpolicy -o json | jq -r '
  .items[] | select(.spec.validate != null) |
  "\(.metadata.name): \(.spec.rules | length) rules"'

# Проверка размера webhook-конфигурации
kubectl get validatingwebhookconfigurations kyverno-validating-webhook-cfg -o json | \
  jq '.webhooks[] | {name: .name, timeoutSeconds: .timeoutSeconds, failurePolicy: .failurePolicy}'
```

**Решения:**

1. **Миграция на CEL (приоритет):**
   ```bash
   # Конвертация простых валидаций в CEL
   kubectl get clusterpolicy <policy-name> -o json | \
     python3 -c "import sys, json; from kyverno_converter import to_cel; print(to_cel(json.load(sys.stdin)))" | \
     kubectl apply -f -
   ```

2. **Оптимизация webhook-конфигурации:**
   ```yaml
   apiVersion: admissionregistration.k8s.io/v1
   kind: ValidatingWebhookConfiguration
   metadata:
     name: kyverno-validating-webhook-cfg
   webhooks:
     - name: kyverno.example.com
       timeoutSeconds: 30  # Увеличить с 10 до 30
       clientConfig:
         service:
           name: kyverno-svc
           namespace: kyverno
       failurePolicy: Ignore  # Для некритичных политик
       matchPolicy: Exact
   ```

3. **Использование GlobalContext для кэширования:**
   ```yaml
   apiVersion: v2.kyverno.io/v1
   kind: ValidatingPolicy
   metadata:
     name: check-image-registry
   spec:
     globalContext:
       apiCalls:
         - name: "trusted-registries"
           urlPath: "/api/v1/namespaces/kube-system/configmaps/trusted-registries"
           jmesPath: "data.registries | split(',')"
     validations:
       - expression: "object.spec.containers.all(c, has(c.image) && globalContext.trusted-registries.exists(r, startsWith(c.image, r)))"
   ```

### Сценарий 2: Горизонтальное масштабирование

**Проблема:** Admission Controller не справляется с нагрузкой при 1000+ подов.

**Методика бенчмаркинга:**

```bash
# 1. Запуск нагрузочного теста
kubectl run kyverno-bench --image=busybox --restart=Never -- \
  sh -c 'for i in $(seq 1 1000); do kubectl create deployment test-$i --image=nginx 2>&1 | tail -1; done'

# 2. Сбор метрик во время теста
kubectl top pods -n kyverno
kubectl logs -n kyverno -l app.kubernetes.io/component=admission-controller -f | \
  grep -E "admission|review|duration"

# 3. Анализ результатов
curl -s http://localhost:8080/metrics | grep -E "kyverno_admission_review_duration_seconds"
```

**Конфигурация масштабирования:**

```yaml
# Horizontal Pod Autoscaler для Admission Controller
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: kyverno-admission-hpa
  namespace: kyverno
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: kyverno-admission-controller
  minReplicas: 2
  maxReplicas: 10
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 70
    - type: Pods
      pods:
        metric:
          name: kyverno_admission_requests_total
        target:
          type: AverageValue
          averageValue: "100"
  behavior:
    scaleUp:
      stabilizationWindowSeconds: 60
      policies:
        - type: Percent
          value: 50
          periodSeconds: 60
    scaleDown:
      stabilizationWindowSeconds: 300
      policies:
        - type: Percent
          value: 25
          periodSeconds: 120
```

### Сценарий 3: Оптимизация фонового сканирования

**Проблема:** Background Scan Performance снижается при 10,000+ ресурсов.

**Диагностика:**

```bash
# Проверка частоты сканирования
kubectl get clusterpolicy -o json | jq -r '
  .items[] | "\(.metadata.name): \(.spec.background) (\(.spec.scanDisabled // false))"'

# Мониторинг времени сканирования
kubectl port-forward -n kyverno svc/kyverno-svc-metrics 8080:8080
curl -s http://localhost:8080/metrics | grep kyverno_background_scan_duration

# Проверка размера PolicyReport
kubectl get polr -A -o json | jq '[.items[].results | length] | add'
```

**Решения:**

1. **Отключение фонового сканирования для некритичных политик:**
   ```yaml
   apiVersion: v2.kyverno.io/v1
   kind: ValidatingPolicy
   metadata:
     name: low-priority-check
   spec:
     background: false  # Отключить фоновое сканирование
     scanDisabled: true  # Отключить триггерное сканирование
   ```

2. **Настройка интервала сканирования:**
   ```bash
   # Аргументы deployment
   args:
     - --backgroundScanPeriod=600  # 10 минут (по умолчанию 10)
     - --scanControllerMaxQPS=10   # Ограничение QPS
     - --scanControllerBurst=50    # Burst для spike
   ```

3. **Использование_PAUSE для тяжелых политик:**
   ```yaml
   metadata:
     annotations:
       kyverno.io/ignore: "true"  # Временно игнорировать политику
   ```

### Сценарий 4: Оптимизация памяти при большом количестве политик

**Проблема:** OOM контроллера при 200+ политик.

**Мониторинг:**

```bash
# Текущее использование памяти
kubectl top pods -n kyverno

# История использования
kubectl get pods -n kyverno -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.status.containerStatuses[0].lastState.terminated.reason}{"\n"}{end}'
```

**Оптимизации:**

1. **Разделение контроллеров:**
   ```yaml
   # Отдельные deployment для разных типов политик
   apiVersion: apps/v1
   kind: Deployment
   metadata:
     name: kyverno-webhook-mutation
   spec:
     replicas: 1
     template:
       spec:
         containers:
           - name: kyverno
             args:
               - --enableMutationWebhook=true
               - --enableValidatingWebhook=true
   ```

2. **Ограничение кэша:**
   ```yaml
   args:
     - --maxControllerWorkers=10
     - --cacheSyncTimeout=5m
     - --clientRateLimitQPS=100
     - --clientRateLimitBurst=50
   ```

---

## Дополнительная информация

### Бенчмарк-тесты (⬡ KBench)

Методика тестирования производительности Kyverno:

```bash
# Репозиторий: https://github.com/kyverno/kbench
# Запуск теста
./kbench.sh --mode=webhook --policies=100 --resources=10000

# Результаты (пример)
# ┌────────────────────┬──────────┬──────────┬──────────┐
# │ Тест               │ P50      │ P95      │ P99      │
# ├────────────────────┼──────────┼──────────┼──────────┤
# │ Admission (10)     │ 12ms     │ 25ms     │ 45ms     │
# │ Admission (50)     │ 35ms     │ 75ms     │ 120ms    │
# │ Admission (100)    │ 65ms     │ 150ms    │ 280ms    │
# │ Background Scan    │ 120s     │ 300s     │ 600s     │
# │ Resource Usage     │ 256Mi    │ 512Mi    │ 768Mi    │
# └────────────────────┴──────────┴──────────┴──────────┘
```

### См. также
- [Диагностика проблем](./troubleshooting.md) — методология поиска причин
- [Фоновое сканирование](./background.md) — настройка интервалов
- [CEL-политики](./policies/definitions_and_concepts.md) — миграция на v2
- [Мультикластер](./multi-cluster.md) — масштабирование на несколько кластеров
