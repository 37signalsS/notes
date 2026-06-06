# Изменение ресурсов подов без перезапуска (In-Place Pod Resize)

## Определения

**In-Place Pod Resize** — функция Kubernetes, позволяющая изменять ресурсы (`requests` и `limits` CPU/memory — запросы и лимиты центрального процессора и оперативной памяти) у запущенных подов без их пересоздания.

**GA (General Availability)** — статус стабильной функции, доступной для промышленного (production) использования. Стабилизирована в Kubernetes 1.35.

## Основные концепции

### Исторический контекст

**До Kubernetes 1.35:**

* Изменение ресурсов пода требовало перезапуска всех контейнеров.
* Приводило к простоям, потере состояния и дополнительной нагруке на кластер.
* VPA (Vertical Pod Autoscaler) мог только рекомендовать изменения или перезапускать поды.

**С Kubernetes 1.35:**

* `kubelet` применяет изменения ресурсов без перезагрузки контейнеров.
* Изменения вступают в силу немедленно для новых процессов.
* Существующие процессы могут продолжать использовать старые лимиты до следующего запуска.

### Принцип работы

1. Пользователь обновляет `resources` в спецификации Pod/Deployment.
2. API-сервер принимает изменения и обновляет объект Pod.
3. `kubelet` обнаруживает изменения и применяет их к контейнеру.
4. Cgroups контейнера обновляются с новыми лимитами.
5. Новые процессы используют обновлённые ресурсы.

### Ограничения функции

| Поддерживается | Не поддерживается |
|----------------|-------------------|
| CPU requests/limits | Изменение количества CPU (hotplug) |
| Memory requests/limits | Уменьшение memory limits ниже текущего потребления |
| Динамическое применение | Ephemeral storage (требуется перезапуск) |
| Работа с VPA | Изменение других ресурсов (GPU, hugepages) |

## Практические сценарии

### Сценарий 1: Ручное увеличение памяти для пода

```bash
# Обновление ресурсов пода напрямую
kubectl patch pod my-app-pod --type='merge' -p '{
  "spec": {
    "containers": [{
      "name": "app",
      "resources": {
        "requests": {
          "memory": "512Mi",
          "cpu": "250m"
        },
        "limits": {
          "memory": "1Gi",
          "cpu": "500m"
        }
      }
    }]
  }
}'
# → pod/my-app-pod patched
```

### Сценарий 2: Обновление ресурсов через Deployment

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: my-app
spec:
  replicas: 3
  selector:
    matchLabels:
      app: my-app
  template:
    metadata:
      labels:
        app: my-app
    spec:
      containers:
      - name: app
        image: my-app:latest
        resources:
          requests:
            memory: "256Mi"
            cpu: "100m"
          limits:
            memory: "512Mi"
            cpu: "200m"
```

**Применение изменений:**

```bash
# Обновление Deployment
kubectl apply -f deployment.yaml
# → deployment.apps/my-app configured

# Проверка статуса обновления
kubectl rollout status deployment/my-app
# → deployment "my-app" successfully rolled out

# Проверка ресурсов подов
kubectl get pod my-app-xyz -o jsonpath='{.spec.containers[0].resources}'
# → {"limits":{"cpu":"200m","memory":"512Mi"},"requests":{"cpu":"100m","memory":"256Mi"}}
```

### Сценарий 3: Использование с VPA (рекомендуемый подход)

```yaml
apiVersion: autoscaling.k8s.io/v1
kind: VerticalPodAutoscaler
metadata:
  name: my-app-vpa
spec:
  targetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: my-app
  
  # Режим Auto использует In-Place Pod Resize
  updatePolicy:
    updateMode: "Auto"
    minReplicas: 2
  
  resourcePolicy:
    containerPolicies:
      - containerName: '*'
        minAllowed:
          cpu: 50m
          memory: 64Mi
        maxAllowed:
          cpu: "2"
          memory: "4Gi"
        controlledResources:
          - cpu
          - memory
```

**Преимущества комбинации:**

* VPA автоматически подбирает оптимальные ресурсы.
* In-Place Pod Resize применяет изменения без простоя.
* Критические сервисы остаются доступными во время обновления.

### Сценарий 4: Обработка пиковых нагрузок

```yaml
# Deployment с базовыми ресурсами
apiVersion: apps/v1
kind: Deployment
metadata:
  name: batch-processor
spec:
  replicas: 5
  template:
    spec:
      containers:
      - name: processor
        image: batch:latest
        resources:
          requests:
            cpu: "500m"
            memory: "1Gi"
          limits:
            cpu: "1"
            memory: "2Gi"
---
# CronJob для временного увеличения ресурсов
apiVersion: batch/v1
kind: CronJob
metadata:
  name: scale-up-resources
spec:
  schedule: "0 2 * * *"  # Ежедневно в 02:00
  jobTemplate:
    spec:
      template:
        spec:
          containers:
          - name: kubectl
            image: bitnami/kubectl:latest
            command:
            - /bin/sh
            - -c
            - |
              kubectl patch deployment batch-processor --type='merge' -p '{
                "spec": {
                  "template": {
                    "spec": {
                      "containers": [{
                        "name": "processor",
                        "resources": {
                          "requests": {"cpu": "1", "memory": "2Gi"},
                          "limits": {"cpu": "2", "memory": "4Gi"}
                        }
                      }]
                    }
                  }
                }
              }'
          restartPolicy: OnFailure
```

### Диагностика и мониторинг

#### Проверка поддержки In-Place Pod Resize

```bash
# Проверка версии Kubernetes
kubectl version --short
# → Client Version: v1.35.0
# → Server Version: v1.35.0

# Проверка функции в кластере
kubectl get apiservice v1.apps -o jsonpath='{.status.conditions[?(@.type=="Available")].status}'
# → True

# Проверка kubelet на узлах
kubectl get nodes -o jsonpath='{range .items[*]}{.metadata.name}: {.status.nodeInfo.kubeletVersion}{"\n"}{end}'
# → node-1: v1.35.0
# → node-2: v1.35.0
```

#### Мониторинг изменений ресурсов

```bash
# Отслеживание событий обновления ресурсов
kubectl get events --field-selector reason=UpdatedResources
# → LAST SEEN   TYPE     REASON             OBJECT           MESSAGE
# → 2m          Normal   UpdatedResources   pod/my-app-pod   Container resources updated in-place

# Проверка применённых ресурсов
kubectl top pods --containers
# → POD          CONTAINER   CPU(cores)   MEMORY(bytes)
# → my-app-pod   app         150m         300Mi

# Детальная информация о поде
kubectl describe pod my-app-pod | grep -A 10 "Limits/Requests"
# → Limits:
# →   cpu:     500m
# →   memory:  1Gi
# → Requests:
# →   cpu:     250m
# →   memory:  512Mi
```

### Лучшие практики

* **Тестируйте в staging** — проверяйте поведение приложения перед production.
* **Мониторьте OOMKilled** — при уменьшении memory limits следите за OOM (Out Of Memory — нехватка памяти).
* **Используйте с VPA** — автоматизируйте подбор ресурсов через VPA + In-Place Resize.
* **Избегайте частых изменений** — слишком частые обновления могут вызвать нестабильность.
* **Проверяйте совместимость** — убедитесь, что runtime (среда выполнения) поддерживает функцию.
* **Настройте алерты** — на поды с OOMKilled после изменения лимитов.

## Дополнительная информация

### Интеграции

In-Place Pod Resize работает в связке с другими компонентами: [VPA](vpa_detailed.md) в режиме `Auto` использует функцию для применения рекомендаций без перезапуска, [HPA](HPA/index.md) масштабирует количество подов, пока In-Place Resize оптимизирует ресурсы каждого пода, а [Cluster Autoscaler](cluster_autoscaler_detailed.md) реагирует на изменения `requests` при масштабировании кластера.

### Ограничения

* **Требуется Kubernetes 1.35+** — функция GA только с этой версии.
* **Поддержка runtime** — containerd и CRI-O (CRI — Container Runtime Interface) поддерживают, Docker требует проверки.
* **Не для всех ресурсов** — только CPU и memory, не работает с ephemeral storage.
* **Существующие процессы** — могут продолжать использовать старые лимиты до перезапуска.

### Влияние на различные типы приложений

| Тип приложения | Влияние | Рекомендации |
|----------------|---------|--------------|
| Stateless (веб-серверы) | Минимальное | Безопасно применять |
| Stateful (базы данных) | Среднее | Требуется тестирование |
| Batch-обработка | Низкое | Рекомендуется |
| Real-time (стриминг) | Среднее | Проверить потерю соединений |
| Java (JVM) | Высокое | JVM (Java Virtual Machine) может не увидеть изменения |
