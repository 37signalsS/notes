# Изменение ресурсов подов без перезапуска (In-Place Pod Resize)

Механизм In-Place Pod Resize позволяет изменять запросы (`requests`) и лимиты (`limits`) ресурсов (CPU, память) для запущенных контейнеров без пересоздания пода и перезапуска процессов. Это критически важная функция для обеспечения непрерывной работы stateful-приложений и тяжелых рабочих нагрузок.

## Определения

*   **In-Place Pod Resize** — функция Kubernetes, позволяющая изменять ресурсы запущенных подов без их пересоздания.
*   **GA (General Availability)** — статус стабильной функции. Стабилизирована в Kubernetes 1.35.
*   **resizePolicy** — параметр в спецификации контейнера, определяющий, требуется ли перезапуск контейнера для применения новых значений ресурсов (`NotRequired` или `RestartContainer`).
*   **allocatedResources** — поле в статусе контейнера, отражающее объем ресурсов, который узловые компоненты (kubelet) фактически выделили контейнеру в данный момент.
*   **Status.Resize** — поле в статусе пода, указывающее на текущее состояние процесса изменения ресурсов (`Proposed`, `InProgress`, `Infeasible`, `Deferred`).

## Основные концепции

### Исторический контекст

**До Kubernetes 1.35:**
* Изменение ресурсов пода требовало перезапуска всех контейнеров.
* Приводило к простоям, потере состояния и дополнительной нагрузке на кластер.
* VPA (Vertical Pod Autoscaler) мог только рекомендовать изменения или перезапускать поды.

**С Kubernetes 1.35 (стабильная версия):**
* Kubelet применяет изменения ресурсов без перезагрузки контейнеров через механизмы cgroups.
* Изменения вступают в силу немедленно для лимитов CPU и памяти (throttle/OOM).
* Поддержка на уровне runtime (containerd 1.7+, CRI-O 1.27+).

### Принцип работы

1.  **Обновление спецификации**: Пользователь или контроллер (например, VPA) меняет `resources` в объекте Pod.
2.  **Валидация**: API-сервер проверяет корректность запроса.
3.  **Принятие (Proposed)**: Kubelet на узле видит изменение и оценивает, достаточно ли свободных ресурсов на ноде для удовлетворения новых `requests`.
4.  **Применение (InProgress)**: Kubelet обновляет настройки контейнера в runtime и параметры cgroups.
5.  **Завершение**: Статус `allocatedResources` обновляется до целевых значений, а флаг `resize` очищается.

### Механизм управления (resizePolicy)

Для каждого ресурса можно настроить индивидуальную политику применения изменений в поле `spec.containers[].resizePolicy`.

*   **NotRequired** (по умолчанию): Изменения применяются «на лету» через cgroups. Процесс внутри контейнера продолжает работать без прерывания.
*   **RestartContainer**: Контейнер будет принудительно перезапущен kubelet для применения новых параметров.

### Состояния процесса (Status.Resize)

| Состояние | Описание |
| :--- | :--- |
| **Proposed** | Запрос получен, но еще не принят kubelet (например, из-за нехватки ресурсов на узле). |
| **InProgress** | Kubelet в процессе применения изменений к runtime. |
| **Infeasible** | Запрос отклонен, так как узел не может предоставить требуемые ресурсы. |
| **Deferred** | Применение отложено (например, если требуется перезапуск, но он запрещен). |

### Ограничения функции

| Поддерживается | Не поддерживается |
| :--- | :--- |
| CPU requests/limits | Изменение количества CPU (hotplug на уровне ОС внутри контейнера) |
| Memory requests/limits | Уменьшение memory limits ниже текущего потребления (RSS) процесса |
| Динамическое применение | Ephemeral storage (требуется перезапуск) |
| Работа с VPA | Изменение других ресурсов (GPU, HugePages) |

## Практические сценарии

### Сценарий 1: Ручное увеличение памяти для пода

```bash
# Обновление ресурсов пода напрямую через patch
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

При использовании Deployment изменение ресурсов в шаблоне пода (`template`) приведет к обновлению всех подов. Благодаря In-Place Resize, это может произойти без пересоздания подов, если контроллер и версия K8s поддерживают бесшовный переход.

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: my-app
spec:
  replicas: 3
  template:
    spec:
      containers:
      - name: app
        image: my-app:latest
        resizePolicy:
          - resourceName: cpu
            restartPolicy: NotRequired
          - resourceName: memory
            restartPolicy: NotRequired
        resources:
          requests:
            memory: "256Mi"
            cpu: "100m"
          limits:
            memory: "512Mi"
            cpu: "200m"
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
  updatePolicy:
    updateMode: "Auto" # Использует In-Place Pod Resize для применения рекомендаций
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

### Сценарий 4: Обработка пиковых нагрузок через CronJob

Временное увеличение ресурсов для выполнения тяжелых задач внутри существующих подов без их пересоздания.

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: scale-up-resources
spec:
  schedule: "0 2 * * *"
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

## Диагностика и мониторинг

### Проверка поддержки и статуса

```bash
# Проверка реально выделенных ресурсов (поле status)
kubectl get pod <pod-name> -o jsonpath='{.status.containerStatuses[0].allocatedResources}'

# Проверка статуса ресайза
kubectl get pod <pod-name> -o jsonpath='{.status.resize}'

# Отслеживание событий изменения
kubectl get events --field-selector reason=UpdatedResources
```

### Типичные ошибки
* `0/1 nodes are available: 1 node(s) didn't match Pod resources` — при увеличении `requests` на узле не осталось места.
* `OOMKilled` сразу после ресайза — лимит памяти был опущен ниже текущего потребления приложения.

## Лучшие практики

* **Тестируйте в staging** — проверяйте, как ваше приложение реагирует на изменение лимитов CPU (throttling).
* **Мониторьте RSS** — перед уменьшением лимита памяти убедитесь, что приложение не потребляет больше.
* **Используйте cgroups v2** — это обязательное условие для корректной работы лимитов памяти без перезапуска.
* **Приоритет NotRequired** — используйте эту политику для всех современных языков программирования (Go, Python, NodeJS, Java 17+).
* **Избегайте "флаттеринга"** — не меняйте ресурсы слишком часто (чаще раза в несколько минут).

## Дополнительная информация

### Влияние на различные типы приложений

| Тип приложения | Влияние | Рекомендации |
| :--- | :--- | :--- |
| **Stateless** | Минимальное | Безопасно применять с `NotRequired`. |
| **Stateful (БД)** | Среднее | Полезно для вертикального масштабирования без разрыва соединений. |
| **Java (JVM)** | Высокое | Старые версии JVM могут не увидеть изменения `MaxRAM` без перезапуска. Требуется Java 17+ или `RestartContainer`. |
| **Batch-задачи** | Низкое | Идеально для динамического выделения ресурсов под конкретный этап обработки. |

### См. также
* **[Vertical Pod Autoscaler (VPA)](./vpa_detailed.md)** — автоматизация управления ресурсами.
* **[QoS классы и лимиты](../Scheduling/qos_limit_and_requests.md)** — теоретическая база ресурсов.
* **[Horizontal Pod Autoscaler (HPA)](./HPA/index.md)** — дополняет вертикальное масштабирование.
