# Изменение ресурсов подов без перезапуска (In-Place Pod Resize)

Механизм In-Place Pod Resize позволяет изменять запросы (`requests`) и лимиты (`limits`) вычислительных ресурсов (CPU, память) для запущенных контейнеров без пересоздания пода и перезапуска процессов. Это критически важная функция для обеспечения непрерывной работы stateful-приложений, баз данных и тяжелых рабочих нагрузок при автомасштабировании.

## Определения

*   **In-Place Pod Resize** — нативная функция Kubernetes, обновляющая ресурсы контейнеров «на лету» через механизмы ядра Linux (`cgroups`).
*   **GA (General Availability)** — функция признана стабильной и включена по умолчанию начиная с **Kubernetes 1.35** (до этого — Alpha в 1.27, Beta в 1.31).
*   **resizePolicy** — параметр в спецификации контейнера, определяющий, как `kubelet` должен применять изменения (`NotRequired` или `RestartContainer`).
*   **allocatedResources** — поле в `status.containerStatuses`, показывающее объем ресурсов, фактически выделенных узлом в текущий момент времени.
*   **Status.Resize** — индикатор состояния транзакции изменения ресурсов (`Proposed`, `InProgress`, `Infeasible`, `Deferred`).
*   **Cgroup v2** — современная подсистема ядра Linux, обязательная для корректной работы изменения лимитов оперативной памяти без сбоев.

---

## Предварительные требования (Prerequisites)

### Версии компонентов

| Компонент | Минимальная версия | Примечание |
| :--- | :--- | :--- |
| Kubernetes | 1.31+ (Beta), 1.35+ (GA) | Для GA — 1.35+, включение флага не требуется |
| Kubelet | Соответствует версии кластера | Должен иметь включенный feature gate `InPlacePodVerticalScaling` (до 1.35) |
| Container Runtime | containerd 1.7+, CRI-O 1.27+ | Должен поддерживать `UpdateContainerResources` CRI API |
| Ядро Linux | 5.15+ с cgroup v2 | Обязательно для memory resize без нестабильности |

### Проверка готовности кластера

```bash
# Проверка версии кластера
kubectl version --short
# → Client Version: v1.35.x
# → Server Version: v1.35.x

# Проверка версии kubelet на узлах
kubectl get nodes -o wide
# → убедиться, что KERNEL-VERSION >= 5.15

# Проверка версии containerd на узлах
kubectl get nodes -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.status.nodeInfo.containerRuntimeVersion}{"\n"}{end}'
# → containerd://1.7.x

# Проверка что cgroup v2 активен (на узле)
kubectl debug node/<node-name> -it --image=alpine -- cat /sys/fs/cgroup/cgroup.controllers
# → cpu memory io pids  (наличие контроллеров = cgroup v2)
```

### Ограничения среды

*   **ResourceQuota:** при In-Place Resize учитываются `requests` в квотах немедленно. Увеличение `requests` может быть заблокировано ResourceQuota, если превышен лимит неймспейса.
*   **LimitRange:** если в неймспейсе настроен LimitRange, новые значения должны соответствовать его ограничениям.
*   **PriorityClass:** изменение ресурсов не влияет на приоритет пода при вытеснении (eviction priority определяется исходя из `requests` на момент создания).

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

**Валидация применения:**

```bash
# Проверка что ресайз применен успешно
kubectl get pod critical-worker-0 -o jsonpath='{.status.containerStatuses[0].allocatedResources}'
# → map[cpu:500m memory:1Gi]

# Проверка что статус ресайза очищен (успешное завершение)
kubectl get pod critical-worker-0 -o jsonpath='{.status.resize}'
# → <пусто> (пусто = успешно применено)

# Проверка событий
kubectl get events --field-selector involvedObject.name=critical-worker-0 --field-selector reason=ResizeSuccessful
# → <timestamp> ResizeSuccessful ...
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

**Применение и валидация:**

```bash
# Применение изменений
kubectl apply -f deployment.yaml
# → deployment.apps/golang-api configured

# Проверка что поды НЕ пересозданы (возраст не изменился)
kubectl get pods -l app=golang-api -o custom-columns=NAME:.metadata.name,AGE:.status.startTime
# → поды сохраняют исходный startTime

# Проверка allocatedResources для всех подов
kubectl get pods -l app=golang-api -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.status.containerStatuses[0].allocatedResources}{"\n"}{end}'
# → golang-api-xxx    map[cpu:200m memory:512Mi]
# → golang-api-yyy    map[cpu:200m memory:512Mi]
# → golang-api-zzz    map[cpu:200m memory:512Mi]
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

**Валидация работы VPA:**

```bash
# Проверка рекомендаций VPA
kubectl describe vpa optimized-database-vpa
# → Recommendation:
# →    Container Recommendations:
# →      Container Name: postgres
# →      Lower Bound:
# →        Cpu:     250m
# →        Memory:  256Mi
# →      Target:
# →        Cpu:     500m
# →        Memory:  512Mi

# Проверка что поды получили новые ресурсы
kubectl get pods -l app=postgres-db -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.status.containerStatuses[0].allocatedResources}{"\n"}{end}'
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

**Дополнительно — CronJob для отката ресурсов:**

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: scale-down-resources
spec:
  schedule: "0 6 * * *" # Откат в 06:00
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
                          "requests": {"cpu": "250m", "memory": "512Mi"},
                          "limits": {"cpu": "500m", "memory": "1Gi"}
                        }
                      }]
                    }
                  }
                }
              }'
          restartPolicy: OnFailure
```

### Сценарий 5: Откат изменений (Cleanup)

Если необходимо вернуть исходные ресурсы, применяется аналогичный PATCH с исходными значениями.

```bash
# Просмотр текущих значений перед откатом
kubectl get pod my-app-0 -o jsonpath='{.spec.containers[0].resources}'
# → map[limits:map[cpu:1 memory:2Gi] requests:map[cpu:500m memory:1Gi]]

# Откат к исходным значениям
kubectl patch pod my-app-0 --type='merge' -p '{
  "spec": {
    "containers": [{
      "name": "app",
      "resources": {
        "requests": {
          "memory": "256Mi",
          "cpu": "100m"
        },
        "limits": {
          "memory": "512Mi",
          "cpu": "200m"
        }
      }
    }]
  }
}'
# → pod/my-app-0 patched
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

### Python
*   Интерпретатор CPython не имеет встроенного механизма ограничения памяти. Увеличение лимита через In-Place Resize безопасно — процесс сможет использовать больше памяти при необходимости.
*   Для приложений с ручным управлением памятью (numpy, pandas) — увеличение лимита позволяет избежать OOM при обработке больших датасетов.

### .NET
*   Начиная с .NET 6+, рантайм нативно поддерживает container awareness и корректно считывает лимиты из cgroups.
*   Для динамического изменения лимита памяти используйте переменную окружения `DOTNET_GCHeapHardLimit` или `DOTNET_GCConserveMemory`.

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
# → map[limits:map[cpu:500m memory:1Gi] requests:map[cpu:250m memory:512Mi]]

# 2. Проверка фактически выделенных (Allocated) ресурсов на узле:
kubectl get pod my-app-0 -o jsonpath='{.status.containerStatuses[0].allocatedResources}'
# → map[cpu:500m memory:1Gi]

# 3. Анализ событий (почему ресайз завис или выдал Infeasible):
kubectl get events --field-selector involvedObject.name=my-app-0 | grep Resize
# → <timestamp> ResizeSuccessful ...
# → <timestamp> ResizeInProgress ...

# 4. Проверка текущего статуса ресайза:
kubectl get pod my-app-0 -o jsonpath='{.status.resize}'
# → Proposed / InProgress / Infeasible / Deferred / <пусто>

# 5. Массовый аудит всех подов с ожидаемым ресайзом:
kubectl get pods --all-namespaces -o json | jq '.items[] | select(.status.resize != null) | {name: .metadata.name, namespace: .metadata.namespace, resize: .status.resize}'
```

### Мониторинг через Prometheus

Ключевые метрики для мониторинга In-Place Resize:

```promql
# Поды с ожидаемым ресайзом (status.resize не пустой)
kube_pod_status_resize{namespace="production"}

# Поды в состоянии Infeasible
kube_pod_status_resize{namespace="production", resize="Infeasible"}

# Разница между запрошенными и выделенными ресурсами (alert если > 0)
(kube_pod_container_resource_requests{resource="cpu"} - on(namespace, pod) kube_pod_container_resource_allocated{resource="cpu"}) > 0
```

**Настройка алерта:**

```yaml
groups:
  - name: in_place_resize
    rules:
      - alert: PodResizeStuck
        expr: kube_pod_status_resize != 0
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Pod {{ $labels.pod }} resize stuck in state {{ $labels.resize }}"
```

---

## Troubleshooting: типичные ошибки и решения

### Ошибка 1: Ресайз завис в состоянии `Proposed`

**Причины:**
*   Kubelet не работает или не отвечает на узле
*   Проблема с сетевой связностью между API-сервером и Kubelet

**Диагностика:**

```bash
# Проверка статуса Kubelet на узле
kubectl get nodes
# → статус узла должен быть Ready

# Проверка логов Kubelet
journalctl -u kubelet -f | grep -i resize
```

**Решение:**
*   Перезапустите Kubelet: `systemctl restart kubelet`
*   Проверьте сетевые политики между API-сервером и узлом

### Ошибка 2: Ресайз завис в состоянии `InProgress`

**Причины:**
*   Container Runtime (containerd/CRI-O) не отвечает на CRI-запрос
*   Баг в рантайме

**Диагностика:**

```bash
# Проверка статуса containerd
systemctl status containerd

# Проверка логов containerd
journalctl -u containerd -f | grep -i update
```

**Решение:**
*   Перезапустите containerd: `systemctl restart containerd`
*   Обновите containerd до версии 1.7.5+

### Ошибка 3: Статус `Infeasible`

**Причины:**
*   На узле нет свободных ресурсов для увеличения `requests`
*   Превышен `NodeAllocatable` лимит

**Диагностика:**

```bash
# Проверка доступных ресурсов узла
kubectl describe node <node-name> | grep -A 10 "Allocated resources"

# Проверка NodeAllocatable
kubectl get node <node-name> -o jsonpath='{.status.allocatable}'
```

**Решение:**
*   Увеличьте емкость узла (добавьте ресурсы)
*   Используйте Cluster Autoscaler для добавления нового узла
*   VPA в режиме `InPlaceOrRecreate` автоматически выселит под для переезда

### Ошибка 4: Уменьшение memory limits не применяется

**Причины:**
*   Текущее потребление памяти (RSS) процесса превышает новый лимит
*   Kubelet блокирует операцию для предотвращения OOM

**Диагностика:**

```bash
# Проверка текущего потребления памяти
kubectl top pod my-app-0
# → my-app-0    1500Mi

# Попытка уменьшить до 1Gi — будет заблокирована
```

**Решение:**
*   Дождитесь снижения потребления памяти приложением
*   Используйте `resizePolicy: RestartContainer` — Kubelet перезапустит контейнер с новым лимитом (приложение должно корректно обрабатывать перезапуск)

### Ошибка 5: ResourceQuota блокирует увеличение `requests`

**Причины:**
*   В неймспейсе настроена ResourceQuota с жесткими лимитами
*   Увеличение `requests` превышает квоту

**Диагностика:**

```bash
# Проверка квот неймспейса
kubectl describe resourcequota -n <namespace>
```

**Решение:**
*   Увеличьте квоту ResourceQuota
*   Уменьшите `requests` других подов для освобождения квоты

---

## Лучшие практики (2026)

1.  **Cgroup v2 обязателен:** Не пытайтесь использовать In-Place Resize для памяти на старых ядрах Linux с cgroup v1. Это приведет к нестабильности и багам при попытке уменьшить лимиты.
2.  **Защита от OOM при даунскейле:** Kubelet не позволит уменьшить `limits.memory` ниже текущего потребления (RSS) процесса. Запрос зависнет в `InProgress` или выдаст ошибку. Сначала приложение должно освободить память, и только потом VPA сможет ужать лимит.
3.  **Сочетание с Cluster Autoscaler:** Если In-Place Resize упирается в статус `Infeasible` из-за нехватки места на узле, вам потребуется комбинация VPA (который перезапустит под) и Cluster Autoscaler (который добавит новый узел).
4.  **Мониторинг:** Настройте алертинг на метрику разницы между `spec.resources` и `status.allocatedResources`. Если разница существует дольше 5 минут, значит механизм ресайза сломан.
5.  **Тестируйте Throttling:** При уменьшении CPU Limit приложение не упадет, но начнет троттлить. Убедитесь, что ваше приложение корректно обрабатывает снижение производительности (например, не рвет тайм-ауты соединений).
6.  **Настройка resizePolicy под приложение:** Всегда явно указывайте `resizePolicy` в спецификации контейнера. Для stateful-приложений с JVM используйте `RestartContainer` для памяти, чтобы избежать рассинхронизации между cgroup и Heap.
7.  **Проверка ResourceQuota:** Перед включением VPA в режиме `Auto` убедитесь, что ResourceQuota неймспейса позволяет увеличение `requests`.

---

## Дополнительная информация

### Влияние на различные типы приложений

| Тип приложения | Влияние | Рекомендации |
| :--- | :--- | :--- |
| **Stateless API (Go/Rust)** | Минимальное | Идеально для In-Place Resize. Безопасно применять с `NotRequired`. |
| **Stateful (СУБД, Cache)** | Высокое | Критически полезно для вертикального масштабирования (Scale-Up) кэша или БД без потери кворума и разрыва пула коннектов. |
| **Legacy (Java 8)** | Блокирующее | Использовать только `resizePolicy: RestartContainer`. |
| **Batch-задачи** | Положительное | Позволяет поднять CPU Limit только на время тяжелого этапа вычислений (см. Сценарий 4). |
| **Node.js приложения** | Среднее | Увеличение лимита спасет от OOMKilled на уровне ядра, но не от `heap out of memory` внутри V8. Требуется перезапуск для изменения `--max-old-space-size`. |

### Edge Cases и известные особенности

1.  **Множественные контейнеры в поде:** Если один контейнер имеет `resizePolicy: RestartContainer`, а другой — `NotRequired`, ресайз применяется независимо для каждого контейнера.
2.  **Init-контейнеры:** In-Place Resize не применяется к init-контейнерам — они уже завершили работу к моменту применения изменений.
3.  **Ephemeral containers:** Ресайз не затрагивает ephemeral containers (используемые для отладки через `kubectl debug`).
4.  **Pod Priority:** Изменение `requests` через In-Place Resize не влияет на приоритет пода при eviction. Priority определяется исходя из `requests` на момент создания пода.
5.  **Одновременный HPA + VPA:** Не используйте HPA и VPA одновременно на одних и тех же метриках (CPU/Memory) — это приведет к конфликту масштабирования. Используйте HPA для кастомных метрик, VPA для CPU/Memory.

### См. также
* **[Vertical Pod Autoscaler (VPA)](./vpa_detailed.md)** — основной инструмент, генерирующий запросы на In-Place Resize.
* **[QoS классы и лимиты](../Scheduling/qos_limit_and_requests.md)** — глубокое погружение в классы обслуживания и cgroups.
* **[Horizontal Pod Autoscaler (HPA)](./HPA/index.md)** — как совмещать вертикальное и горизонтальное масштабирование.
* **[OOMKilled: диагностика](../Troubleshooting/Common_Errors/oomkilled_pods.md)** — решение проблем с утечками памяти.
