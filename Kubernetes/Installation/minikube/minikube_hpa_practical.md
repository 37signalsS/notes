# Minikube: настройка Horizontal Pod Autoscaler (HPA)

## Определения

**HPA (Horizontal Pod Autoscaler)** — контроллер Kubernetes, автоматически масштабирующий количество реплик Deployment/ReplicaSet на основе метрик (CPU, память, кастомные). Подробнее: [HPA: Concepts](../../../Autoscaling/HPA/hpa_concepts.md).

**Metrics Server** — компонент, собирающий метрики ресурсов (CPU, память) из kubelet. Обязателен для работы HPA на базе CPU/Memory. В Minikube включается как аддон.

**Кастомные метрики (Custom Metrics)** — метрики приложения (запросы/сек, очередь сообщений), экспортируемые через Metrics Adapter (Prometheus Adapter, KEDA). Подробнее: [HPA: Advanced](../../../Autoscaling/HPA/hpa_advanced.md).

**Target** — целевое значение метрики. HPA рассчитывает желаемое количество реплик: `replicas = ceil(currentReplicas * currentMetric / targetMetric)`.

---

## Базовые концепции

### HPA в Minikube: особенности

| Параметр | Production | Minikube |
| :--- | :--- | :--- |
| **Узлы** | Много (10+) | 1 (по умолчанию) |
| **Масштабирование подов** | Распределение по узлам | Все поды на одном узле |
| **Кастомные метрики** | Prometheus Adapter / KEDA | Prometheus Adapter (через LGTM-стек) |
| **Минимальные ресурсы** | Автоплатформа | Ограничены памятью/CPU |
| **Тестирование** | Ограничено | Полная лаборатория |

### Когда тестировать HPA в Minikube

- Разработка и отладка метрик приложения перед деплоем в production.
- Проверка корректности настройки `requests`/`limits` (влияние на расчет HPA).
- Тестирование поведения при忽落ании метрик (metric unavailability).
- Валидация `behavior` (custom scaling rules) перед production-применением.

---

## Практические сценарии

### Шаг 1: Включение Metrics Server

```bash
# Включение аддона Metrics Server
minikube addons enable metrics-server

# Проверка подов metrics-server
kubectl get pods -n kube-system | grep metrics-server
# → metrics-server-...   1/1     Running

# Ожидание сбора метрик (~30 сек)
kubectl top nodes
# → NAME       CPU(cores)   CPU%   MEMORY(bytes)   MEMORY%
# → minikube   150m         3%     1024Mi          12%

kubectl top pods -A
# → NAME                                CPU(cores)   MEMORY(bytes)
# → metrics-server-...                  5m           20Mi
```

### Шаг 2: Тестовое приложение с метриками CPU

```yaml
# php-apache-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: php-apache
spec:
  replicas: 1
  selector:
    matchLabels:
      app: php-apache
  template:
    metadata:
      labels:
        app: php-apache
    spec:
      containers:
      - name: php-apache
        image: registry.k8s.io/hpa-example
        ports:
        - containerPort: 80
        resources:
          requests:
            cpu: 200m
            memory: 128Mi
          limits:
            cpu: 500m
            memory: 256Mi
---
apiVersion: v1
kind: Service
metadata:
  name: php-apache
spec:
  selector:
    app: php-apache
  ports:
  - port: 80
    targetPort: 80
  type: ClusterIP
```

### Шаг 3: Создание HPA

```yaml
# hpa-cpu.yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: php-apache
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: php-apache
  minReplicas: 1
  maxReplicas: 10
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 50
  behavior:
    scaleDown:
      stabilizationWindowSeconds: 60
      policies:
      - type: Pods
        value: 1
        periodSeconds: 60
    scaleUp:
      stabilizationWindowSeconds: 0
      policies:
      - type: Percent
        value: 100
        periodSeconds: 15
```

```bash
kubectl apply -f php-apache-deployment.yaml
kubectl apply -f hpa-cpu.yaml

# Проверка HPA
kubectl get hpa
# → NAME         REFERENCE                 TARGETS   MINPODS   MAXPODS   REPLICAS
# → php-apache   Deployment/php-apache     0%/50%    1         10        1
```

### Шаг 4: Генерация нагрузки (тест масштабирования)

```bash
# Запуск нагрузочного теста в отдельном поде
kubectl run load-generator --image=busybox:latest -- /bin/sh -c \
  "while true; do wget -q -O- http://php-apache; done"

# Наблюдение за HPA (в отдельном терминале)
kubectl get hpa php-apache --watch
# → NAME         REFERENCE                 TARGETS   MINPODS   MAXPODS   REPLICAS
# → php-apache   Deployment/php-apache     5%/50%    1         10        1
# → php-apache   Deployment/php-apache     45%/50%   1         10        1
# → php-apache   Deployment/php-apache     80%/50%   1         10        3  ← scale up
# → php-apache   Deployment/php-apache     50%/50%   1         10        5

# Проверка подов
kubectl get pods -l app=php-apache
# → NAME                          READY   STATUS    RESTARTS   AGE
# → php-apache-6d4f5c5x7b-abc1   1/1     Running   0          5m
# → php-apache-6d4f5c5x7b-def2   1/1     Running   0          30s
# → php-apache-6d4f5c5x7b-ghi3   1/1     Running   0          30s

# Остановка нагрузки
kubectl delete pod load-generator

# Наблюдение за scale-down (через stabilizationWindowSeconds)
kubectl get hpa php-apache --watch
# → php-apache   Deployment/php-apache     2%/50%    1         10        5
# → php-apache   Deployment/php-apache     0%/50%    1         10        3  ← scale down
```

### Шаг 5: HPA с кастомными метриками (Prometheus Adapter)

> **Примечание:** Требуется Prometheus, установленный через LGTM-стек. Подробнее: [LGTM-стек на Minikube](../../../Installation/LGTM_Stack/lgtm_otel_minikube_overview.md).

```yaml
# custom-metric-pod.yaml — приложение, экспортирующее метрику
apiVersion: apps/v1
kind: Deployment
metadata:
  name: custom-metrics-app
spec:
  replicas: 1
  selector:
    matchLabels:
      app: custom-metrics-app
  template:
    metadata:
      labels:
        app: custom-metrics-app
      annotations:
        prometheus.io/scrape: "true"
        prometheus.io/port: "8080"
    spec:
      containers:
      - name: app
        image: busybox:latest
        command:
        - /bin/sh
        - -c
        - |
          # Генерация фиктивной метрики http_requests_per_second
          while true; do
            VALUE=$(($RANDOM % 100))
            echo "http_requests_per_second $VALUE" | curl --data-binary @- http://prometheus:9091/metrics/job/custom_app
            sleep 5
          done
        ports:
        - containerPort: 8080
        resources:
          requests:
            cpu: 100m
            memory: 64Mi
          limits:
            cpu: 200m
            memory: 128Mi
```

```yaml
# hpa-custom-metric.yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: custom-metrics-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: custom-metrics-app
  minReplicas: 1
  maxReplicas: 5
  metrics:
  - type: Pods
    pods:
      metric:
        name: http_requests_per_second
      target:
        type: AverageValue
        averageValue: "50"
```

### Шаг 6: Диагностика HPA

```bash
# Детальная информация о HPA
kubectl describe hpa php-apache
# → Conditions:
# →   Type            Status  Reason
# →   AbleToScale     True    ReadyNewReplicaSet
# →   ScalingActive   True    ValidMetricFound

# Причины, почему HPA НЕ масштабирует:
# 1. MetricsServer не установлен
kubectl get deployment metrics-server -n kube-system

# 2. Нет метрик (поды не потребляют ресурсы)
kubectl top pods -l app=php-apache

# 3. Достигнут maxReplicas
kubectl get hpa php-apache -o jsonpath='{.spec.maxReplicas}'

# 4. HPA в degraded состоянии
kubectl get hpa php-apache -o jsonpath='{.status.conditions}'
```

```bash
# Проверка target thresholds
kubectl get hpa -o custom-columns=NAME:.metadata.name,TARGETS:.status.currentMetrics[*].resource.target.averageUtilization,MIN:.spec.minReplicas,MAX:.spec.maxReplicas

# Просмотр событий HPA
kubectl get events --field-selector reason=ScalingActive --sort-by='.lastTimestamp'
```

### Очистка

```bash
kubectl delete hpa php-apache custom-metrics-hpa
kubectl delete deployment php-apache custom-metrics-app
kubectl delete service php-apache
kubectl delete pod load-generator --ignore-not-found
```

---

## Дополнительная информация

### См. также

- [HPA: Concepts](../../../Autoscaling/HPA/hpa_concepts.md) — теория и принципы работы
- [HPA: Advanced](../../../Autoscaling/HPA/hpa_advanced.md) — кастомные метрики, behavior
- [HPA: Scenarios](../../../Autoscaling/HPA/hpa_scenarios.md) — production-сценарии
- [Metrics Server](../../../MonitoringLogging/metrics-server.md) — установка и настройка
- [LGTM-стек на Minikube](../../../Installation/LGTM_Stack/lgtm_otel_minikube_overview.md) — Prometheus для кастомных метрик

### Полезные ссылки

- [Horizontal Pod Autoscaler Walkthrough](https://kubernetes.io/docs/tasks/run-application/horizontal-pod-autoscale-walkthrough/) — официальный туториал
- [HPA Design](https://github.com/kubernetes/design-proposals-archive/blob/main/autoscaling/hpa.md) — архитектурный proposal
