# Изменение ресурсов подов без перезапуска (In-Place Pod Resize)

Механизм In-Place Pod Resize позволяет изменять запросы (`requests`) и лимиты (`limits`) вычислительных ресурсов (CPU, память) для запущенных контейнеров без пересоздания пода и перезапуска процессов. Это критически важная функция для обеспечения непрерывной работы stateful-приложений, баз данных и тяжелых рабочих нагрузок при автомасштабировании.

## Определения

*   **In-Place Pod Resize** — нативная функция Kubernetes, обновляющая ресурсы контейнеров «на лету» через механизмы ядра Linux (`cgroups`).
*   **GA (General Availability)** — функция признана стабильной и включена по умолчанию начиная с **Kubernetes 1.35**.
*   **resizePolicy** — параметр в спецификации контейнера, определяющий, как `kubelet` должен применять изменения (`NotRequired` или `RestartContainer`).
*   **allocatedResources** — поле в `status.containerStatuses`, показывающее объем ресурсов, фактически выделенных узлом в текущий момент времени.
*   **Status.Resize** — индикатор состояния транзакции изменения ресурсов (`Proposed`, `InProgress`, `Infeasible`, `Deferred`).
*   **Cgroup v2** — современная подсистема ядра Linux, обязательная для корректной работы изменения лимитов оперативной памяти без сбоев.

---

## Основные концепции

### Архитектура и принцип работы

1.  **Запрос (API):** Пользователь или автоскейлер (VPA) выполняет PATCH запрос к объекту Pod, изменяя секцию `spec.containers[].resources`.
2.  **Proposed:** API-сервер принимает запрос. Поле `status.resize` устанавливается в `Proposed`.
3.  **Анализ Kubelet:** `kubelet` на узле, где запущен под, перехватывает изменение. Он оценивает доступную емкость узла. Если `requests` увеличены, а свободного места на узле нет, статус меняется на `Infeasible`.
4.  **InProgress:** Если ресурсы доступны, `kubelet` обращается к Container Runtime (containerd/CRI-O) и обновляет параметры `cgroups` для запущенного процесса.
5.  **Завершение:** Kubelet обновляет поле `allocatedResources` в статусе пода до новых значений и очищает поле `status.resize`.

### Влияние на QoS классы

Изменение ресурсов "на лету" **не меняет** исходный QoS (Quality of Service) класс пода, который был присвоен ему при создании.
*   Если под был создан как `Burstable`, он останется `Burstable`, даже если вы попытаетесь выровнять его `requests` и `limits` (что для нового пода дало бы `Guaranteed`).
*   Это архитектурное решение защищает кластер от непредсказуемого поведения планировщика и проблем с приоритетами вытеснения.

### Механизм управления (resizePolicy)

В спецификации контейнера можно определить политику применения для каждого типа ресурсов индивидуально:

```yaml
resizePolicy:
  - resourceName: cpu
    restartPolicy: NotRequired # Изменять "на лету"
  - resourceName: memory
    restartPolicy: RestartContainer # Обязательно перезапускать контейнер
```

| Политика | Описание | Когда применять |
| :--- | :--- | :--- |
| **`NotRequired`** | (По умолчанию). Kubelet обновляет cgroups без убийства процесса PID 1. | Для большинства современных приложений (Go, Node.js, Python, Java 17+). |
| **`RestartContainer`** | Kubelet принудительно перезапустит контейнер с новыми лимитами (под при этом не удаляется). | Устаревший софт, скрипты, считывающие ресурсы только при старте (например, Java 8). |

### Ограничения функции

| Поддерживается | НЕ поддерживается |
| :--- | :--- |
| CPU requests/limits | CPU Hotplug (изменение количества виртуальных ядер на уровне ОС) |
| Memory requests/limits | Уменьшение memory limits ниже текущего потребления (RSS) процесса |
| Интеграция с VPA | Ephemeral storage (Дисковое пространство) |
| Поддержка в containerd 1.7+ | Изменение Extended Resources (GPU, HugePages, SRIOV) |

---

## Практические сценарии

### Сценарий 1: Ручное увеличение памяти для пода при угрозе OOM

При угрозе OOMKilled администратор может экстренно поднять лимиты пода без прерывания обработки запросов (например, для долгой задачи экспорта БД).

```bash
# Обновление ресурсов пода напрямую через patch
kubectl patch pod critical-worker-0 --type='merge' -p '{
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
# → pod/critical-worker-0 patched
```

### Сценарий 2: Обновление ресурсов через Deployment

При использовании Deployment изменение ресурсов в шаблоне пода (`template`) приведет к обновлению всех подов. Благодаря In-Place Resize, это происходит без пересоздания подов (Rolling Update не инициирует удаление старых ReplicaSet), что экономит время старта приложения.

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: golang-api
spec:
  replicas: 3
  template:
    spec:
      containers:
      - name: api
        image: golang-api:v2
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

### Сценарий 3: Интеграция с Vertical Pod Autoscaler (Рекомендуемый подход)

Использование `In-Place Resize` совместно с VPA в режиме `Auto` (или `InPlaceOrRecreate`) — стандарт конфигурации кластеров в 2026 году. VPA автоматически патчит поды, а Kubelet применяет изменения.

```yaml
apiVersion: autoscaling.k8s.io/v1
kind: VerticalPodAutoscaler
metadata:
  name: optimized-database-vpa
spec:
  targetRef:
    apiVersion: apps/v1
    kind: StatefulSet
    name: postgres-db
  updatePolicy:
    updateMode: "InPlaceOrRecreate" # Сначала пробует In-Place, если не влезает на узел - Recreate
  resourcePolicy:
    containerPolicies:
      - containerName: '*'
        minAllowed:
          cpu: 50m
          memory: 64Mi
        maxAllowed:
          cpu: "2"
          memory: "4Gi"
        controlledValues: RequestsAndLimits
```

### Сценарий 4: Обработка пиковых нагрузок через CronJob

Временное динамическое выделение ресурсов для выполнения тяжелых задач внутри существующих подов без их пересоздания. Например, ночной пересчет индексов.

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: scale-up-resources
spec:
  schedule: "0 2 * * *" # Запуск в 02:00
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
              # Увеличиваем лимиты существующего Deployment "на лету"
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

---

## Специфика рантаймов (Среды выполнения)

Изменение `cgroups` со стороны Kubelet не означает, что приложение внутри контейнера автоматически "увидит" новые ресурсы.

### Java (JVM)
*   **Проблема:** JVM считывает доступную память при старте и выставляет размер Heap (`Xmx`). Если Kubelet увеличит лимит контейнера "на лету", JVM не увеличит Heap автоматически.
*   **Решение:** Начиная с Java 17, используйте флаги `-XX:MaxRAMPercentage=80.0`. Несмотря на это, для динамического изменения Heap без рестарта требуется поддержка ZGC/Shenandoah и специфичные настройки JMX. Часто для JVM баз данных проще оставить `resizePolicy: RestartContainer` для памяти.

### Go (Golang)
*   **Проблема:** Ранее Go GC (сборщик мусора) ориентировался на доступную память хоста.
*   **Решение:** С версии Go 1.19 введена переменная `GOMEMLIMIT`. Если вы используете In-Place Resize, используйте библиотеку (например, `automemlimit`), которая отслеживает изменения в `/sys/fs/cgroup/memory.max` и динамически обновляет `GOMEMLIMIT` в рантайме.

### Node.js (V8)
*   Требуется передача флага `--max-old-space-size`. V8 не умеет менять его динамически, поэтому увеличение лимита спасет от OOMKilled на уровне ядра Linux, но не спасет от `Fatal error: heap out of memory` внутри самого V8.

---

## Диагностика и мониторинг

### Состояния транзакции ресайза (status.resize)

| Состояние | Описание и диагностика |
| :--- | :--- |
| **`Proposed`** | API-сервер принял патч, Kubelet еще не отреагировал. Если зависло — проблема с Kubelet. |
| **`InProgress`** | Kubelet запросил CRI (containerd) изменить cgroups. Если зависло — проблема на уровне Container Runtime. |
| **`Infeasible`** | **Частая ошибка**. Вы запросили увеличение `requests`, но на текущем узле нет свободного CPU/RAM. Под останется работать со старыми ресурсами. VPA в режиме `InPlaceOrRecreate` в ответ на этот статус выполнит `Evict` пода для переезда на узел побольше. |
| **`Deferred`** | Применение отложено (например, если требуется перезапуск, но он сейчас невозможен). |

### Команды для аудита

```bash
# 1. Проверка запрошенных (Desired) ресурсов в спецификации:
kubectl get pod my-app-0 -o jsonpath='{.spec.containers[0].resources}'

# 2. Проверка фактически выделенных (Allocated) ресурсов на узле:
kubectl get pod my-app-0 -o jsonpath='{.status.containerStatuses[0].allocatedResources}'

# 3. Анализ событий (почему ресайз завис или выдал Infeasible):
kubectl get events --field-selector involvedObject.name=my-app-0 | grep Resize
```

---

## Лучшие практики (2026)

1.  **Cgroup v2 обязателен:** Не пытайтесь использовать In-Place Resize для памяти на старых ядрах Linux с cgroup v1. Это приведет к нестабильности и багам при попытке уменьшить лимиты.
2.  **Защита от OOM при даунскейле:** Kubelet не позволит уменьшить `limits.memory` ниже текущего потребления (RSS) процесса. Запрос зависнет в `InProgress` или выдаст ошибку. Сначала приложение должно освободить память, и только потом VPA сможет ужать лимит.
3.  **Сочетание с Cluster Autoscaler:** Если In-Place Resize упирается в статус `Infeasible` из-за нехватки места на узле, вам потребуется комбинация VPA (который перезапустит под) и Cluster Autoscaler (который добавит новый узел).
4.  **Мониторинг:** Настройте алертинг на метрику разницы между `spec.resources` и `status.allocatedResources`. Если разница существует дольше 5 минут, значит механизм ресайза сломан.
5.  **Тестируйте Throttling:** При уменьшении CPU Limit приложение не упадет, но начнет троттлить. Убедитесь, что ваше приложение корректно обрабатывает снижение производительности (например, не рвет тайм-ауты соединений).

---

## Дополнительная информация

### Влияние на различные типы приложений

| Тип приложения | Влияние | Рекомендации |
| :--- | :--- | :--- |
| **Stateless API (Go/Rust)** | Минимальное | Идеально для In-Place Resize. Безопасно применять с `NotRequired`. |
| **Stateful (СУБД, Cache)** | Высокое | Критически полезно для вертикального масштабирования (Scale-Up) кэша или БД без потери кворума и разрыва пула коннектов. |
| **Legacy (Java 8)** | Блокирующее | Использовать только `resizePolicy: RestartContainer`. |
| **Batch-задачи** | Положительное | Позволяет поднять CPU Limit только на время тяжелого этапа вычислений (см. Сценарий 4). |

### См. также
* **[Vertical Pod Autoscaler (VPA)](./vpa_detailed.md)** — основной инструмент, генерирующий запросы на In-Place Resize.
* **[QoS классы и лимиты](../Scheduling/qos_limit_and_requests.md)** — глубокое погружение в классы обслуживания и cgroups.
* **[Horizontal Pod Autoscaler (HPA)](./HPA/index.md)** — как совмещать вертикальное и горизонтальное масштабирование.
* **[OOMKilled: диагностика](../Troubleshooting/Common_Errors/oomkilled_pods.md)** — решение проблем с утечками памяти.
