# HPA: Практические сценарии

**Актуально для:** Kubernetes 1.28–1.35 (API autoscaling/v2)

В данном документе представлены проверенные типовые конфигурации (YAML-манифесты) горизонтального масштабирования подов (Horizontal Pod Autoscaler, HPA) для различных архитектурных профилей нагрузки в Kubernetes, а также пошаговые инструкции по их внедрению, валидации, эксплуатации и диагностике.

Материал ориентирован на инженеров DevOps, SRE и системных администраторов инфраструктуры Kubernetes на выделенных серверах (Bare-Metal и On-Premise) без использования проприетарных облачных сервисов и надстроек.

Для получения теоретических основ см. **[HPA: Основные концепции](./hpa_concepts.md)**. Тонкая настройка ядра Linux, cgroups и поведение при сетевом дребезге — в **[HPA: Продвинутые темы](./hpa_advanced.md)**. Настройка экспорта кастомных метрик — в **[Prometheus Adapter: настройка и интеграция](./prometheus_adapter_setup.md)**. Вводный обзор раздела — в **[HPA: Главная](./index.md)**.

---

## Определения

**Horizontal Pod Autoscaler (HPA v2)** — контроллер в составе `kube-controller-manager`, непрерывно сопоставляющий фактические показатели нагрузки с целевыми значениями и изменяющий поле `spec.replicas` целевого контроллера через подресурс `/scale`. Интерфейс `autoscaling/v2` является стабильным стандартом (GA с Kubernetes 1.23; устаревшие версии `v2beta1` и `v2beta2` удалены в 1.26).

**ScaleTargetRef** — блок спецификации HPA (`spec.scaleTargetRef`), определяющий целевой управляемый ресурс (`apiVersion`, `kind`, `name`). Должен указывать строго на объект верхнего уровня (`Deployment` или `StatefulSet`). Указание на дочерний `ReplicaSet` недопустимо, так как нарушает процесс обновления (Rollout) и приводит к масштабированию неактивного набора подов.

**Подресурс `/scale` (Scale Subresource)** — REST-эндпоинт Kubernetes API (`/apis/apps/v1/namespaces/{ns}/{resource}/{name}/scale`), абстрагирующий управление числом реплик (`spec.replicas` и `status.replicas`). Позволяет HPA изменять количество экземпляров без перезаписи остальной спецификации пода.

**Resource Requests** — гарантированный объем процессорного времени (`cpu`) и оперативной памяти (`memory`), зарезервированный планировщиком (kube-scheduler) для каждого контейнера. Служит базовой величиной (100%) для расчета процента утилизации: `(фактическое_потребление / requests) × 100%`. Без указания `requests` расчет процента невозможен, и HPA переходит в статус `<unknown>`.

**Working Set Memory** — используемый Kubelet и cgroups показатель оперативной памяти контейнера, равный общему потреблению за вычетом неактивного файлового кэша (`container_memory_working_set_bytes = usage - inactive_file`). Именно эта метрика передается через Metrics Server и используется HPA для оценки утилизации памяти.

**Секция `behavior`** — блок спецификации HPA v2 (`spec.behavior`), обеспечивающий раздельное управление скоростью и динамикой масштабирования вверх (`scaleUp`) и вниз (`scaleDown`), включая длительность окон стабилизации (`stabilizationWindowSeconds`) и выбор между конкурирующими правилами (`selectPolicy`).

**Окно стабилизации (Stabilization Window)** — временной интервал в прошлом, за который контроллер анализирует сгенерированные рекомендации по масштабированию. Для `scaleDown` алгоритм выбирает наибольшее число реплик за окно, предотвращая преждевременное удаление подов при кратковременных спадах трафика.

**ContainerResource** — тип метрики в API `autoscaling/v2`, позволяющий вычислять утилизацию ресурсов конкретного именованного контейнера в поде, изолируя метрики основного приложения от влияния ресурсоемких вспомогательных контейнеров (sidecars: Envoy, Fluent-bit, лог-агенты).

**Pod Disruption Budget (PDB)** — объект политики Kubernetes (`policy/v1`), ограничивающий количество одновременно недоступных подов при добровольных вытеснениях (дрейн узла, обновление, масштабирование вниз).

**Порог толерантности (Tolerance)** — алгоритмический диапазон нечувствительности HPA (по умолчанию 10% или `0.1`), в пределах которого изменение метрики не вызывает изменения числа реплик, предотвращая паразитные колебания.

---

## Архитектура и механизмы работы сценариев

### Конвейер передачи метрик на On-Premise инфраструктуре

В On-Premise и Bare-Metal кластерах горизонтальное масштабирование функционирует через трехуровневый конвейер:

```
[Контейнеры / cgroups v2] 
       │ (сбор каждые 10-15с)
       ▼
   [cAdvisor / Kubelet] 
       │ 
       ▼
[Metrics Server] ──► [Aggregator API: metrics.k8s.io] ──► [HPA Controller]
                                                                │
[Prometheus] ────► [Prometheus Adapter / KEDA]                  │ (запись в /scale)
       │                 │                                      ▼
       └──────────► [custom.metrics.k8s.io] ────────────► [Deployment / StatefulSet]
                    [external.metrics.k8s.io]                   │
                                                                ▼
                                                        [kube-scheduler]
                                                                │
                                                        [Bare-Metal Nodes]
```

1. **Ресурсные метрики (`Resource`, `ContainerResource`):** Kubelet на каждом узле собирает данные о потреблении CPU и Working Set памяти через cAdvisor. `Metrics Server` опрашивает Kubelet узлов, агрегирует данные в оперативной памяти и публикует их через API `metrics.k8s.io`.
2. **Пользовательские метрики подов и объектов (`Pods`, `Object`):** Приложения или контроллеры (например, Ingress-NGINX) экспортируют метрики в Prometheus. `Prometheus Adapter` преобразует PromQL-запросы в API `custom.metrics.k8s.io`.
3. **Внешние метрики (`External`):** Показатели брокеров сообщений (RabbitMQ, Kafka, Redis), находящихся внутри кластера или на внешних серверах, регистрируются через `external.metrics.k8s.io` с помощью Prometheus Adapter или KEDA.

### Алгоритм вычисления целевого числа реплик

Контроллер HPA выполняет расчет по формуле:

$$\text{desiredReplicas} = \left\lceil \text{currentReplicas} \times \left( \frac{\text{currentMetricValue}}{\text{desiredMetricValue}} \right) \right\rceil$$

Если отношение $\frac{\text{currentMetricValue}}{\text{desiredMetricValue}}$ находится в интервале от $0.9$ до $1.1$ (порог толерантности $10\%$), контроллер признает текущее состояние сбалансированным и не выполняет изменений.

### Особенности масштабирования в On-Premise окружении

В отличие от облачных платформ, где дефицит ресурсов узлов компенсируется автоматическим заказом виртуальных машин через Cloud Cluster Autoscaler, инфраструктура Bare-Metal обладает фиксированным пулом вычислительных мощностей:

- **Лимит аллокации (Allocatable):** Параметр `maxReplicas` в HPA должен быть строго согласован с суммарным объемом `cpu.allocatable` и `memory.allocatable` рабочих узлов кластера.
- **ResourceQuota:** Если HPA вычисляет масштабирование вверх, превышающее лимиты пространства имен (`ResourceQuota`), планирование новых подов блокируется со статусом `FailedCreate`, а в HPA фиксируется условие `ScalingLimited: True`.
- **Влияние на дисковую и сетевую подсистему:** При интенсивном масштабировании на Bare-Metal узлах возрастает нагрузка на сетевые интерфейсы (CRI / CNI) и дисковые хранилища при загрузке слоев контейнеров, поэтому поды должны использовать минимальные легковесные базовые образы.

---

## Практические сценарии и конфигурация

### Предварительные требования

Перед развертыванием любого сценария убедитесь в готовности инфраструктурных компонентов:

1. **Работоспособность Metrics Server:**
   ```bash
   kubectl get apiservice v1beta1.metrics.k8s.io
   # → NAME                     SERVICE                      AVAILABLE   AGE
   # → v1beta1.metrics.k8s.io   kube-system/metrics-server   True        45d

   kubectl top nodes
   # → NAME       CPU(cores)   CPU%   MEMORY(bytes)   MEMORY%
   # → worker-01  420m         10%    8192Mi          25%
   # → worker-02  510m         12%    9420Mi          29%
   ```

2. **Заданные `resources.requests`:**
   Каждый контейнер пода должен иметь явные значения `requests`. Пример рабочего блока:
   ```yaml
   resources:
     requests:
       cpu: "250m"
       memory: "256Mi"
     limits:
       cpu: "1000m"
       memory: "512Mi"
   ```

3. **Корректные пробы готовности (`readinessProbe`):**
   HPA включает в формулу расчета только поды в состоянии `Ready`. Если приложение стартует медленно или не имеет probes, метрики не прогретых подов исказят результат расчета.

4. **Адаптер метрик для нестандартных сценариев:**
   Для метрик RPS, очередей и времени отклика должен быть установлен и зарегистрирован `Prometheus Adapter` или `KEDA` с валидным статусом APIService (`v1beta1.custom.metrics.k8s.io` / `v1beta1.external.metrics.k8s.io`).

---

### Алгоритм внедрения HPA в Production

Чек-лист для SRE и инженеров сопровождения:

1. **Профилирование сервиса под нагрузкой:** Определение критического ресурса (CPU-bound, I/O-bound, память).
2. **Фиксация базовой линии:** Настройка `resources.requests` на уровне 75–80-го перцентиля реального потребления в спокойном состоянии.
3. **Выбор целевой утилизации:** Установка целевого порога на уровне 60–70% для CPU, чтобы оставить запас (Headroom) для обработки всплесков во время разгона новых подов.
4. **Конфигурация PDB:** Развертывание `PodDisruptionBudget` для защиты минимального кворума доступности при сжатии пула.
5. **Настройка политик стабилизации:** Увеличение `scaleDown.stabilizationWindowSeconds` до 300–600 секунд для исключения дребезга.
6. **Интеграция с GitOps:** Добавление исключения `ignoreDifferences` для `.spec.replicas` в ArgoCD или Flux.

---

### Сценарий 1: Базовый HPA по процессору (CPU)

Предназначен для классических веб-приложений и API без сохранения состояния (Stateless), где нагрузка линейно транслируется в загрузку процессорных ядер.

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: web-api-cpu-hpa
  namespace: production
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: web-api
  minReplicas: 3
  maxReplicas: 20
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 65
```

**Разбор параметров:**
- `scaleTargetRef`: указывает строго на `Deployment/web-api`.
- `averageUtilization: 65`: контроллер стремится удерживать среднее потребление процессорного времени на уровне 65% от `spec.template.spec.containers[*].resources.requests.cpu`.
- `minReplicas: 3`: гарантия высокой доступности (HA) на случай планового перезапуска узла или падения процесса.
- `maxReplicas: 20`: жесткий верхний предел масштабирования, защищающий кластер от исчерпания ресурсов узлов при аномальных нагрузках.

---

### Сценарий 2: Мультиметрика (CPU и Память) с защитой от OOM

Используется для приложений, чувствительных к утечкам памяти и пиковым нагрузкам по CPU. HPA вычисляет необходимое число реплик для каждого правила независимо и выбирает **максимальное (наиболее безопасное)** значение.

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: backend-multimetric-hpa
  namespace: production
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: order-backend
  minReplicas: 3
  maxReplicas: 15
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 60
    - type: Resource
      resource:
        name: memory
        target:
          type: Utilization
          averageUtilization: 75
  behavior:
    scaleDown:
      stabilizationWindowSeconds: 600
      policies:
        - type: Percent
          value: 10
          periodSeconds: 60
```

**Математика вычисления мультиметрики:**
```
Исходное состояние: 4 реплики.
Метрика CPU: текущая утилизация 85%, цель 60%  ──► ceil(4 × (85 / 60)) = ceil(5.66) = 6 реплик
Метрика Memory: текущая утилизация 68%, цель 75% ──► ceil(4 × (68 / 75)) = ceil(3.62) = 4 реплики

Решение HPA: Max(6, 4) = 6 реплик.
```

**Эксплуатационное предупреждение (SRE Gotcha):**
Многие управляемые среды исполнения (JVM, Golang, Node.js) не возвращают немедленно освобожденную память операционной системе ядра Linux после срабатывания сборщика мусора (GC). Показатель `working_set_bytes` удерживается на высоком уровне длительное время. Использование памяти в качестве единственной метрики HPA может приводить к «залипанию» пула на значении `maxReplicas`. Память в HPA рекомендуется использовать только как вторичный предохранитель с консервативным `scaleDown`.

---

### Сценарий 3: Масштабирование по длине очереди через External Metrics

Применяется для асинхронных фоновых обработчиков (Background Workers), читающих сообщения из очередей RabbitMQ, Kafka или Redis, развернутых в On-Premise инфраструктуре.

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: rabbitmq-consumer-hpa
  namespace: processing
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: email-notification-worker
  minReplicas: 2
  maxReplicas: 40
  metrics:
    - type: External
      external:
        metric:
          name: rabbitmq_queue_messages_ready
          selector:
            matchLabels:
              queue: emails-high-priority
        target:
          type: AverageValue
          averageValue: "150"
```

**Разбор параметров:**
- `type: External`: источник метрики находится за пределами стандартного конвейера Kubelet.
- `metric.selector`: фильтрация конкретной очереди через селектор меток в адаптере.
- `averageValue: "150"`: целевая нагрузка на один под-обработчик. Если в очереди скопилось 3000 сообщений, HPA рассчитает: $\lceil 3000 / 150 \rceil = 20$ реплик.
- Подробнее о паттернах работы с брокерами см. **[Паттерн Workers + Queue](../workers_queue_pattern.md)**.

---

### Сценарий 4: Масштабирование по нагрузке на инстанс (Pods Metrics)

Используется для сервисов, где ключевой метрикой выступает количество входящих HTTP-запросов в секунду (RPS) на конкретный под приложения. Значение агрегируется Prometheus Adapter и делится контроллером HPA на количество готовых подов.

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: api-gateway-rps-hpa
  namespace: gateway
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: api-gateway
  minReplicas: 4
  maxReplicas: 25
  metrics:
    - type: Pods
      pods:
        metric:
          name: http_requests_per_second
        target:
          type: AverageValue
          averageValue: "400"
```

**Особенности работы:**
- Prometheus Adapter суммирует `rate(http_requests_total[2m])` по всем подам с меткой `app=api-gateway`.
- HPA получает суммарное значение из API `custom.metrics.k8s.io` и делит его на текущее количество реплик, сравнивая результат с порогом `averageValue: 400`.
- При резком наплыве трафика (например, 4800 RPS суммарно) целевое число подов составит: $\lceil 4800 / 400 \rceil = 12$ реплик.

---

### Сценарий 5: Масштабирование по метрике внешнего объекта (Object Metrics)

Используется в случаях, когда метрика привязана к самостоятельному объекту Kubernetes (например, суммарный RPS или счетчик активных соединений на объекте `Ingress`).

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: frontend-ingress-hpa
  namespace: frontend
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: web-frontend
  minReplicas: 3
  maxReplicas: 30
  metrics:
    - type: Object
      object:
        describedObject:
          apiVersion: networking.k8s.io/v1
          kind: Ingress
          name: web-main-ingress
        metric:
          name: requests_per_second
        target:
          type: Value
          value: "3000"
```

**Разбор параметров:**
- `type: Object`: метрика считывается со связанного ресурса (`describedObject`), указанного в том же пространстве имен.
- `target.type: Value`: прямое абсолютное значение метрики всего объекта.
- Формула расчета: $\lceil \text{currentReplicas} \times (\text{currentValue} / 3000) \rceil$.

---

### Сценарий 6: Тонкая настройка динамики масштабирования (Behavior)

Настройка профиля масштабирования для критических production-сервисов с мгновенной реакцией на всплески (Burst/Spike traffic) и консервативным, ступенчатым сжатием пула для исключения дребезга (Anti-Flapping).

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: payment-service-behavior-hpa
  namespace: billing
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: payment-processor
  minReplicas: 4
  maxReplicas: 32
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 60
  behavior:
    scaleUp:
      stabilizationWindowSeconds: 0
      policies:
        - type: Percent
          value: 100
          periodSeconds: 15
        - type: Pods
          value: 4
          periodSeconds: 15
      selectPolicy: Max
    scaleDown:
      stabilizationWindowSeconds: 300
      policies:
        - type: Percent
          value: 10
          periodSeconds: 60
        - type: Pods
          value: 2
          periodSeconds: 60
      selectPolicy: Min
```

**Сводка параметров секции `behavior`:**

| Параметр | Направление | Назначение | Рекомендация для On-Premise Production |
|:---|:---|:---|:---|
| `stabilizationWindowSeconds` | `scaleUp` | Фильтрация ложных пиков перед ростом | `0` (мгновенное расширение при всплеске) |
| `stabilizationWindowSeconds` | `scaleDown` | Анализ максимального числа реплик за окно | `300` – `600` секунд (5–10 минут ожидания) |
| `policies.type: Percent` | `scaleUp` | Шаг расширения в процентах от текущего пула | `100%` (удвоение за 15 секунд) |
| `policies.type: Pods` | `scaleUp` | Абсолютный шаг расширения | `4` пода (гарантированный прирост для малых пулов) |
| `policies.type: Percent` | `scaleDown` | Шаг сужения пула в процентах | `10%` за 60 секунд (плавный вывод) |
| `policies.type: Pods` | `scaleDown` | Абсолютный шаг сужения | `1`–`2` пода за период |
| `selectPolicy: Max` | `scaleUp` | Выбор между конкурирующими политиками | Выбирает наибольший шаг (агрессивный рост) |
| `selectPolicy: Min` | `scaleDown` | Выбор между конкурирующими политиками | Выбирает наименьший шаг (осторожный спуск) |

Детальный анализ параметров см. в **[HPA: Продвинутые темы](./hpa_advanced.md)**.

---

### Сценарий 7: Масштабирование по ресурсу конкретного контейнера (ContainerResource)

Используется для подов с ресурсоемкими вспомогательными контейнерами (sidecars: Envoy/Istio-proxy, Fluent-bit, лог-коллекторы). Стандартный тип `Resource` суммирует потребление всех контейнеров в поде, что может приводить к ложному масштабированию из-за активности sidecar.

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: app-container-resource-hpa
  namespace: core
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: order-service
  minReplicas: 3
  maxReplicas: 18
  metrics:
    - type: ContainerResource
      containerResource:
        container: order-api
        name: cpu
        target:
          type: Utilization
          averageUtilization: 70
```

**Особенности применения:**
- Поле `container: order-api` указывает имя контейнера из `spec.template.spec.containers[*].name`.
- Потребление CPU контейнеров `istio-proxy` или `filebeat` полностью игнорируется алгоритмом HPA.
- Контейнер `order-api` обязан иметь заданный `resources.requests.cpu`.

---

### Сценарий 8: HPA для StatefulSet

Масштабирование распределенных воркеров или шардированных очередей, оформленных в виде StatefulSet.

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: stream-worker-statefulset-hpa
  namespace: analytics
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: StatefulSet
    name: stream-worker
  minReplicas: 2
  maxReplicas: 12
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 65
  behavior:
    scaleDown:
      stabilizationWindowSeconds: 600
      policies:
        - type: Pods
          value: 1
          periodSeconds: 120
      selectPolicy: Min
```

**Критические архитектурные правила для StatefulSet:**
1. **Порядок удаления подов:** Kubernetes StatefulSet удаляет поды строго в обратном порядке — начиная с **наибольшего индекса (ordinal)** к наименьшему (например, при 4 репликах сначала удаляется `stream-worker-3`, затем `stream-worker-2`).
2. **Персистентные тома (PVC):** При масштабировании StatefulSet вниз ассоциированные PersistentVolumeClaims **не удаляются автоматически**. Они остаются привязанными в кластере, сохраняя данные. При повторном масштабировании вверх под с тем же индексом подключится к своему старому PVC.
3. **Безопасный шаг scaleDown:** Политика `policies.type: Pods, value: 1` с интервалом `120s` гарантирует последовательное завершение работы подов с завершением локальной обработки данных.
4. Дополнительные детали архитектуры см. в **[Масштабирование StatefulSet](../statefulset_autoscaling.md)**.

---

### Сценарий 9: Связка HPA + Pod Disruption Budget (PDB) в Production

Гарантия непрерывной доступности при плановом обслуживании узлов (дрейн) и одновременном масштабировании вниз.

```yaml
# 1. PodDisruptionBudget: защита минимального кворума
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: user-auth-pdb
  namespace: identity
spec:
  minAvailable: 2
  selector:
    matchLabels:
      app: user-auth
---
# 2. HorizontalPodAutoscaler: согласованное масштабирование
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: user-auth-hpa
  namespace: identity
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: user-auth
  minReplicas: 3
  maxReplicas: 16
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 65
  behavior:
    scaleDown:
      stabilizationWindowSeconds: 300
      policies:
        - type: Pods
          value: 1
          periodSeconds: 45
```

**Координация HPA и PDB:**
- Если в кластере 3 реплики, а PDB требует `minAvailable: 2`, одновременно может быть вытеснен ровно 1 под.
- Пошаговое удаление (`policies.type: Pods, value: 1`) гарантирует, что HPA не попытается запросить падение сразу на 2 пода, что вызвало бы конфликт с PDB.
- См. подробнее **[Pod Disruption Budget](../pod_disruption_budget.md)**.

---

### Сценарий 10: Комбинированные политики Behavior с селекторами SelectPolicy

Сценарий обеспечивает адаптивное поведение: на малых масштабах наращивание происходит фиксированными порциями, а при достижении больших объемов начинает доминировать процентная ставка.

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: adaptive-workload-hpa
  namespace: default
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: dynamic-api
  minReplicas: 2
  maxReplicas: 50
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 60
  behavior:
    scaleUp:
      stabilizationWindowSeconds: 0
      policies:
        - type: Percent
          value: 100
          periodSeconds: 15
        - type: Pods
          value: 4
          periodSeconds: 15
      selectPolicy: Max
    scaleDown:
      stabilizationWindowSeconds: 600
      policies:
        - type: Percent
          value: 10
          periodSeconds: 60
        - type: Pods
          value: 1
          periodSeconds: 60
      selectPolicy: Min
```

**Поведение `selectPolicy: Max` при `scaleUp`:**
- При текущих 2 репликах: `Percent: 100%` дает $+2$ пода (итого 4), `Pods: 4` дает $+4$ пода (итого 6). HPA выбирает `Max` $\rightarrow 6$ подов.
- При текущих 20 репликах: `Percent: 100%` дает $+20$ подов (итого 40), `Pods: 4` дает $+4$ пода (итого 24). HPA выбирает `Max` $\rightarrow 40$ подов.

---

### Сценарий 11: HPA + Ingress-NGINX на Bare-Metal (RPS и Latency P99)

Экспорт метрик контроллером Ingress-NGINX через внутренний эндпоинт Prometheus и масштабирование нижележащего бэкенда.

#### Вариант А: Конфигурация Prometheus Adapter и HPA по RPS

```yaml
# Фрагмент ConfigMap prometheus-adapter для RPS
apiVersion: v1
kind: ConfigMap
metadata:
  name: prometheus-adapter-config
  namespace: monitoring
data:
  config.yaml: |
    rules:
      - seriesQuery: 'nginx_ingress_controller_requests{namespace!="",ingress!=""}'
        resources:
          overrides:
            namespace: {resource: "namespace"}
            ingress: {resource: "ingress", group: "networking.k8s.io", version: "v1"}
        name:
          matches: "^(.*)_requests$"
          as: "ingress_requests_per_second"
        metricsQuery: 'sum(rate(<<.Series>>{<<.LabelMatchers>>}[2m])) by (<<.GroupBy>>)'
---
# HPA: масштабирование сервиса по общему объему входящего RPS на Ingress
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: backend-ingress-rps-hpa
  namespace: apps
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: catalog-service
  minReplicas: 3
  maxReplicas: 30
  metrics:
    - type: Object
      object:
        describedObject:
          apiVersion: networking.k8s.io/v1
          kind: Ingress
          name: catalog-ingress
        metric:
          name: ingress_requests_per_second
        target:
          type: Value
          value: "1500"
```

#### Вариант Б: Масштабирование по Latency P99 (Prometheus Adapter)

```yaml
# Фрагмент правила Prometheus Adapter для квантиля P99
apiVersion: v1
kind: ConfigMap
metadata:
  name: prometheus-adapter-p99-config
  namespace: monitoring
data:
  config.yaml: |
    rules:
      - seriesQuery: 'nginx_ingress_controller_request_duration_seconds_bucket{namespace!="",ingress!=""}'
        resources:
          overrides:
            namespace: {resource: "namespace"}
            ingress: {resource: "ingress", group: "networking.k8s.io", version: "v1"}
        name:
          matches: "^(.*)_bucket$"
          as: "nginx_request_duration_p99"
        metricsQuery: 'histogram_quantile(0.99, sum(rate(<<.Series>>{<<.LabelMatchers>>}[5m])) by (le, <<.GroupBy>>))'
---
# HPA: масштабирование бэкенда при превышении времени ответа P99 > 250 мс
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: catalog-latency-hpa
  namespace: apps
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: catalog-service
  minReplicas: 4
  maxReplicas: 20
  metrics:
    - type: Object
      object:
        describedObject:
          apiVersion: networking.k8s.io/v1
          kind: Ingress
          name: catalog-ingress
        metric:
          name: nginx_request_duration_p99
        target:
          type: Value
          value: "250m"  # 250 миллисекунд (0.25 сек)
  behavior:
    scaleDown:
      stabilizationWindowSeconds: 600
      policies:
        - type: Pods
          value: 1
          periodSeconds: 60
```

---

### Сценарий 12: HPA + Traefik Ingress на On-Premise

Масштабирование сервиса по данным встроенного Prometheus exporter маршрутизатора Traefik.

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: traefik-service-hpa
  namespace: production
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: search-service
  minReplicas: 3
  maxReplicas: 25
  metrics:
    - type: Object
      object:
        describedObject:
          apiVersion: networking.k8s.io/v1
          kind: Ingress
          name: search-ingress
        metric:
          name: traefik_service_requests_total_rate
        target:
          type: Value
          value: "800"
  behavior:
    scaleUp:
      stabilizationWindowSeconds: 0
    scaleDown:
      stabilizationWindowSeconds: 300
      policies:
        - type: Percent
          value: 15
          periodSeconds: 60
```

---

### Сценарий 13: HPA и Graceful Shutdown / Connection Draining при Scale-Down

В On-Premise инфраструктуре при масштабировании вниз резкое завершение подов приводит к сбросу активных соединений (HTTP 502 / TCP RST) на аппаратных балансировщиках и Ingress-контроллерах, так как распространение обновлений `EndpointSlice` по узлам через `kube-proxy` занимает от 1 до 3 секунд.

Для предотвращения деградации Deployment должен содержать перехватчик `preStop`:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: graceful-api
  namespace: production
spec:
  replicas: 3
  selector:
    matchLabels:
      app: graceful-api
  template:
    metadata:
      labels:
        app: graceful-api
    spec:
      terminationGracePeriodSeconds: 60
      containers:
        - name: app
          image: internal-registry.local/apps/graceful-api:v1.4.2
          lifecycle:
            preStop:
              exec:
                # Пауза для удаления пода из EndpointSlices до отправки SIGTERM
                command: ["/bin/sh", "-c", "sleep 15"]
          ports:
            - containerPort: 8080
          resources:
            requests:
              cpu: "300m"
              memory: "512Mi"
---
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: graceful-api-hpa
  namespace: production
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: graceful-api
  minReplicas: 3
  maxReplicas: 15
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 70
  behavior:
    scaleDown:
      stabilizationWindowSeconds: 300
      policies:
        - type: Pods
          value: 1
          periodSeconds: 30
```

**Механика работы:**
1. HPA инициирует уменьшение реплик.
2. Pod переходит в статус `Terminating`.
3. Контроллер эндпоинтов исключает IP-адрес пода из `EndpointSlice`, а Ingress-контроллер перестает направлять на него новые запросы.
4. Выполняется `preStop: sleep 15`, давая время завершиться уже принятым TCP-сессиям.
5. Приложению отправляется сигнал `SIGTERM`.

---

### Сценарий 14: HPA в условиях жестких ResourceQuota на On-Premise

В многопользовательских кластерах пространства имен часто ограничены квотами (`ResourceQuota`). Если HPA рассчитывает увеличение подов, превышающее лимит квоты пространства имен, новые поды блокируются admission-контроллером.

```yaml
# Квота пространства имен
apiVersion: v1
kind: ResourceQuota
metadata:
  name: team-compute-quota
  namespace: team-crm
spec:
  hard:
    requests.cpu: "10"       # Максимум 10 CPU
    requests.memory: "20Gi"  # Максимум 20 GiB памяти
    pods: "30"               # Максимум 30 подов
---
# HPA с жестким ограничением maxReplicas для предотвращения насыщения квоты
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: crm-worker-hpa
  namespace: team-crm
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: crm-worker
  # requests.cpu = 500m. 16 подов = 8 CPU, оставляя 2 CPU на системные сервисы пространства имен
  minReplicas: 2
  maxReplicas: 16
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 70
```

**Диагностика условия `ScalingLimited` при исчерпании квоты:**
При достижении потолка квоты `kube-controller-manager` регистрирует в HPA статус:
```bash
kubectl describe hpa crm-worker-hpa -n team-crm
# → Conditions:
# →   Type            Status  Reason              Message
# →   ----            ------  ------              -------
# →   AbleToScale     True    SucceededGetScale   the HPA controller was able to get the target's current scale
# →   ScalingActive   True    ValidMetricFound    the HPA was able to successfully calculate a replica count
# →   ScalingLimited  True    TooManyReplicas     the desired replica count is more than the maximum replica count
```

---

## Операции и команды

Сводка команд системного администратора и инженера SRE для управления, валидации и мониторинга HPA:

### 1. Создание HPA (декларативно и императивно)

```bash
# Императивное создание базового HPA (быстрый запуск для тестирования)
kubectl autoscale deployment web-api --cpu-percent=70 --min=3 --max=15 -n production
# → horizontalpodautoscaler.autoscaling/web-api autoscaled

# Декларативное применение production-манифеста
kubectl apply -f hpa-manifest.yaml
# → horizontalpodautoscaler.autoscaling/web-api-cpu-hpa created
```

### 2. Мониторинг текущего состояния

```bash
# Просмотр сводки HPA в пространстве имен
kubectl get hpa -n production
# → NAME              REFERENCE          TARGETS   MINPODS   MAXPODS   REPLICAS   AGE
# → web-api-cpu-hpa   Deployment/web-api 42%/65%   3         20        3          12m

# Непрерывный мониторинг в реальном времени при нагрузочном тестировании
kubectl get hpa web-api-cpu-hpa -n production -w
# → NAME              REFERENCE          TARGETS   MINPODS   MAXPODS   REPLICAS   AGE
# → web-api-cpu-hpa   Deployment/web-api 42%/65%   3         20        3          12m
# → web-api-cpu-hpa   Deployment/web-api 78%/65%   3         20        3          13m
# → web-api-cpu-hpa   Deployment/web-api 82%/65%   3         20        5          13m
```

### 3. Глубокая инспекция и события контроллера

```bash
# Просмотр детального описания, текущих метрик и условий (Conditions)
kubectl describe hpa web-api-cpu-hpa -n production
# → Name:                                                  web-api-cpu-hpa
# → Namespace:                                             production
# → Reference:                                             Deployment/web-api
# → Metrics:                                               ( current / target )
# →   resource cpu on pods  (as a percentage of request):  42% (105m) / 65%
# → Min replicas:                                          3
# → Max replicas:                                          20
# → Deployment pods:                                       3 current / 3 desired
# → Conditions:
# →   Type            Status  Reason               Message
# →   ----            ------  ------               -------
# →   AbleToScale     True    ReadyForNewScale     recommended size matches current size
# →   ScalingActive   True    ValidMetricFound     the HPA was able to successfully calculate a replica count
# →   ScalingLimited  False   DesiredWithinRange   the desired count is within the acceptable range
# → Events:
# →   Type    Reason             Age   From                       Message
# →   ----    ------             ----  ----                       -------
# →   Normal  SuccessfulRescale  2m    horizontal-pod-autoscaler  New size: 5; reason: cpu resource utilization (percentage of request) above target
```

### 4. Проверка условий через JSONPath

```bash
# Проверка условия ScalingActive (True = метрики поступают штатно)
kubectl get hpa web-api-cpu-hpa -n production -o jsonpath='{.status.conditions[?(@.type=="ScalingActive")].status}'
# → True

# Получение расчетного желаемого числа реплик
kubectl get hpa web-api-cpu-hpa -n production -o jsonpath='{.status.desiredReplicas}'
# → 5
```

### 5. Прямой опрос API метрик (Диагностика Aggregated API)

```bash
# Проверка доступности сырых метрик Kubelet через Metrics Server
kubectl get --raw "/apis/metrics.k8s.io/v1beta1/namespaces/production/pods" | jq -r '.items[] | {name: .metadata.name, cpu: .containers[].usage.cpu}'
# → { "name": "web-api-5c689d8-8x2jk", "cpu": "125m" }
# → { "name": "web-api-5c689d8-9l4nm", "cpu": "110m" }

# Проверка регистрации Custom Metrics API
kubectl get --raw "/apis/custom.metrics.k8s.io/v1beta1" | jq -r '.resources[].name'
# → pods/http_requests_per_second
# → ingress.networking.k8s.io/ingress_requests_per_second
```

### 6. Процедура безопасного отключения и отката (Rollback / Maintenance)

При возникновении инцидентов или проведении экстренных регламентных работ масштабирование необходимо зафиксировать:

```bash
# Вариант А: Временная фиксация реплик без удаления HPA (через behavior)
kubectl patch hpa web-api-cpu-hpa -n production --type='merge' -p '{"spec":{"behavior":{"scaleUp":{"selectPolicy":"Disabled"},"scaleDown":{"selectPolicy":"Disabled"}}}}'
# → horizontalpodautoscaler.autoscaling/web-api-cpu-hpa patched

# Вариант Б: Полное удаление HPA
kubectl delete hpa web-api-cpu-hpa -n production
# → horizontalpodautoscaler.autoscaling "web-api-cpu-hpa" deleted

# Ручная установка фиксированного количества реплик
kubectl scale deployment web-api --replicas=5 -n production
# → deployment.apps/web-api scaled

# Проверка статуса
kubectl get deployment web-api -n production
# → NAME      READY   UP-TO-DATE   AVAILABLE   AGE
# → web-api   5/5     5            5           30d
```

> **Важно:** При простом удалении HPA контроллер оставляет число реплик на уровне **последнего выполненного расчета**. Оно не возвращается автоматически к исходному значению до создания HPA.

---

## Диагностика и устранение неполадок

### Сводная таблица типовых ошибок

| Ошибка / Симптом | Первопричина | Метод локализации | Решение |
|:---|:---|:---|:---|
| `TARGETS: <unknown>/65%` | У подов отсутствуют `resources.requests`, либо упал `metrics-server` | `kubectl describe hpa`, `kubectl top nodes` | Добавить `requests.cpu/memory` контейнерам. Проверить поды `metrics-server` в `kube-system`. |
| `TARGETS: <unknown>` только для кастомных метрик | Недоступен Prometheus Adapter, ошибка PromQL, или объект не найден | `kubectl get apiservice v1beta1.custom.metrics.k8s.io` | Проверить логи `prometheus-adapter` и доступность Prometheus в кластере. |
| Постоянный дребезг (Flapping / Thrashing) | Отсутствует окно стабилизации на `scaleDown`; малый порог толерантности | `kubectl get events --field-selector involvedObject.kind=HorizontalPodAutoscaler` | Настроить `behavior.scaleDown.stabilizationWindowSeconds: 300` и `policies.type: Percent`. |
| HPA не масштабирует вверх при 100% нагрузке | Достигнут `maxReplicas`, либо квота пространства имен исчерпана | `kubectl describe hpa` (условие `ScalingLimited: True`) | Увеличить `maxReplicas` или расширить `ResourceQuota` в `spec.hard`. |
| `FailedGetResourceMetric: missing request for container` | Sidecar-контейнер (Envoy, Fluent-bit) не имеет заданных `requests` | `kubectl get pod <pod> -o yaml` | Задать `requests` для ВСЕХ контейнеров пода или перейти на метрику `ContainerResource`. |
| ScaleDown заблокирован и поды не удаляются | Слишком жесткий `PodDisruptionBudget` блокирует удаление подов | `kubectl get pdb`, поля `DisruptionsAllowed: 0` | Скорректировать `minAvailable` / `maxUnavailable` в PDB или увеличить число реплик. |
| Изменение реплик перезаписывается каждые 2 минуты | Конфликт GitOps-агента (ArgoCD / Flux) с подресурсом `/scale` | Логи ArgoCD (`OutOfSync` по полю `spec.replicas`) | Добавить `ignoreDifferences` для `/spec/replicas` в манифест `Application`. |

---

### Алгоритм расследования инцидентов (SRE Troubleshooting Checklist)

```
[TARGETS: <unknown>]
       │
       ├─► 1. Проверить Metrics Server:
       │      $ kubectl get pods -n kube-system -l k8s-app=metrics-server
       │      $ kubectl top nodes
       │      Если ошибка сертификатов ──► добавить --kubelet-insecure-tls в deployment.
       │
       ├─► 2. Проверить requests у контейнеров:
       │      $ kubectl get deployment <name> -o jsonpath='{.spec.template.spec.containers[*].resources.requests}'
       │      Если пусто ──► добавить requests.
       │
       └─► 3. Проверить статус подов:
              $ kubectl get pods -l app=<name>
              Если поды в CrashLoopBackOff или ReadinessProbe Failed ──► HPA игнорирует не готовые поды.
```

---

### Граничные случаи (Edge Cases)

1. **Масштабирование во время Rolling Update:**
   При развертывании новой версии Deployment существуют два ReplicaSet. HPA опрашивает суммарные метрики всех готовых подов обоих ReplicaSet и передает команду на изменение размера в Deployment. Deployment масштабирует новый ReplicaSet согласно параметрам `maxSurge` и `maxUnavailable`.
2. **HPA и DaemonSet:**
   HPA категорически не поддерживает `DaemonSet`, так как размер пула жестко определяется планировщиком по количеству подходящих узлов кластера.
3. **Множественные HPA на один ресурс:**
   Kubernetes API допускает создание двух разных HPA для одного Deployment. Это приводит к катастрофическому конфликту: каждый контроллер перезаписывает `/scale`, вызывая хаотическое переключение реплик. Допустим только **один HPA на один объект**.
4. **Масштабирование до 0 реплик:**
   Стандартный HPA в Kubernetes API `autoscaling/v2` **не поддерживает** `minReplicas: 0`. Минимальное допустимое значение — `1`. Для масштабирования неактивных воркеров до 0 на On-Premise инфраструктуре применяется **[KEDA](../keda/keda_concepts.md)**.
5. **Отказ Prometheus или Metrics Server:**
   При недоступности API метрик контроллер HPA не удаляет поды. Он сохраняет текущее значение `replicas` и переходит в аварийный режим, защищая инфраструктуру от каскадного коллапса (Safety Lock).

---

## Лучшие практики

1. **Базовый выбор метрик:** Для подавляющего большинства сервисов начинайте с `Resource: cpu` с целевым значением 60–70%. Это оставляет достаточный запас вычислительной мощности (Headroom) для обработки пиков во время запуска и прогрева новых реплик.
2. **Обязательное наличие Readiness Probes:** Без корректных проверок готовности новый под попадает в балансировку трафика не прогретым, получает всплеск нагрузки, транслирует высокое время ответа и может инициировать ложный повторный цикл `scaleUp`.
3. **Никогда не задавайте `spec.replicas` в манифесте Deployment при использовании HPA:** Поле `replicas` должно быть удалено из YAML Deployment. В противном случае каждый повторный `kubectl apply` или синхронизация CI/CD будет принудительно сбрасывать количество реплик к статическому числу, конфликтуя с HPA.
4. **Конфигурация GitOps (ArgoCD / Flux):** Настройте игнорирование расхождений в манифесте приложения:
   ```yaml
   spec:
     ignoreDifferences:
       - group: apps
         kind: Deployment
         jsonPointers:
           - /spec/replicas
   ```
   Подробнее см. **[GitOps для Autoscaling](../gitops_autoscaling.md)**.
5. **Асимметричный Behavior:** Всегда настраивайте агрессивный `scaleUp` (`stabilizationWindowSeconds: 0`) и консервативный `scaleDown` (`stabilizationWindowSeconds: 300–600`). Это исключает эффект дребезга (flapping).
6. **Обязательная связка с PDB:** Каждый масштабируемый сервис обязан иметь `PodDisruptionBudget`. Минимальный размер пула `minReplicas` должен быть строго больше `minAvailable` в PDB.
7. **Capacity Planning на On-Premise:** Сумма всех `maxReplicas * requests.cpu` не должна превышать суммарный объем доступных ядер рабочих узлов кластера с учетом резерва операционной системы и демонов `kubelet`.

---

## Дополнительная информация

Смежные разделы базы знаний по горизонтальному и смешанному масштабированию в On-Premise инфраструктуре:

- **[HPA: Главная](./index.md)** — архитектурный обзор горизонтального автомасштабирования.
- **[HPA: Основные концепции](./hpa_concepts.md)** — алгоритмы, типы метрик, работа контроллера.
- **[HPA: Продвинутые темы](./hpa_advanced.md)** — глубокая настройка `behavior`, cgroups, сетевые аспекты.
- **[Prometheus Adapter: настройка и интеграция](./prometheus_adapter_setup.md)** — развертывание кастомных метрик в кластере.
- **[HPA: Cost и Right-sizing](./hpa_cost_rightsizing.md)** — оптимизация аппаратных затрат и подбор requests.
- **[Каскадное масштабирование](./cascading_scaling.md)** — предотвращение лавинообразных перегрузок зависимых сервисов.
- **[Масштабирование StatefulSet](../statefulset_autoscaling.md)** — специфика автомасштабирования stateful-нагрузок.
- **[Pod Disruption Budget](../pod_disruption_budget.md)** — обеспечение кворума доступности при сжатии пулов.
- **[GitOps для Autoscaling](../gitops_autoscaling.md)** — устранение конфликтов ArgoCD и Flux с autoscalers.
- **[Устранение неполадок HPA](../../Troubleshooting/Common_Errors/hpa_troubleshooting.md)** — справочник кодов ошибок и пошаговой диагностики.
