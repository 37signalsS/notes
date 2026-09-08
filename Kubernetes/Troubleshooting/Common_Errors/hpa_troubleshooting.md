# Устранение неполадок HPA (Horizontal Pod Autoscaler)

## Определения

**HPA (Horizontal Pod Autoscaler)** — контроллер Kubernetes (`kube-controller-manager`), который периодически запрашивает метрики у Metrics API и изменяет поле `replicas` у целевого объекта через subresource `/scale`. Входит в категорию workload-контроллеров наряду с Deployment, StatefulSet, ReplicaSet.

**HPA Troubleshooting** — процесс выявления и устранения сбоев в работе горизонтального автомасштабировщика подов. HPA работает как «петля управления» (Control Loop), и сбой обычно происходит в конвейере передачи метрик или из-за конфликтов конфигурации.

**Control Loop HPA** — замкнутый цикл, выполняемый с интервалом `--horizontal-pod-autoscaler-sync-period` (по умолчанию **15 секунд**): чтение метрик → расчёт desiredReplicas → запись через `/scale` subresource → ожидание следующего цикла. Цикл декларативен — HPA не знает, что произошло после записи, и полагается на следующую итерацию для оценки результата.

**`desiredReplicas`** — целевое количество реплик, рассчитанное HPA по формуле:

```
desiredReplicas = ceil[currentReplicas × (currentMetricValue / targetMetricValue)]
```

Результат всегда округляется вверх (`ceil`), затем ограничивается диапазоном `[minReplicas, maxReplicas]`. Если формула даёт дробное значение — HPA округлит вверх (предпочитает over-provisioning).

**`<unknown>` в метриках** — состояние, при котором контроллер HPA не может получить текущее значение метрики от API-сервера. Причины: Metrics API недоступен, отсутствует `resources.requests`, RBAC запрещает чтение, метрика ещё не накоплена (cold start), тип метрики не подходит (`External` при наличии только `Resource`).

**Дребезг (Flapping/Thrashing)** — ситуация частого создания и удаления подов из-за резких колебаний метрик или некорректно настроенных окон стабилизации. Симптом: `replicas` колеблется на ±1-2 каждые 1-2 минуты. В крайней форме — петля, в которой HPA увеличивает поды, метрика падает, HPA уменьшает, метрика растёт.

**Stabilization Window** — окно времени (по умолчанию 300 сек для scaleDown, 0 сек для scaleUp), в течение которого HPA удерживает принятое решение, даже если метрика вернулась в норму. Предотвращает «откаты» и снижает churn.

**Toleration (0.1 / 10%)** — минимальное относительное изменение метрики, на которое HPA реагирует. Если разница между текущим и желаемым количеством реплик меньше tolerance, изменение игнорируется. Управляется флагом `--horizontal-pod-autoscaler-tolerance` (по умолчанию `0.1`).

## Алгоритм диагностики

### Шаг 1: Проверка статуса и условий (Conditions)

Это основной источник данных. Изучите секцию `Conditions` в выводе describe:
```bash
kubectl describe hpa <hpa-name>
```

| Условие | Статус: Значение | Что означает |
|:---|:---|:---|
| **`AbleToScale`** | `False`: `FailedGetScale` | HPA не может найти целевой объект (Deployment/StatefulSet) или нет прав RBAC. |
| **`ScalingActive`** | `False`: `FailedGetResourceMetric` | Проблема сбора метрик (Metrics API недоступен или пуст). |
| **`ScalingLimited`** | `True`: `TooManyReplicas` | Достигнут `maxReplicas`. Масштабирование выше невозможно. |

> В версии `autoscaling/v2` дополнительно появляются условия `AbleToScale` с reason `BackoffLimitReached` (внутреннее ограничение на скорость масштабирования), `ScalingActive` с reason `FailedGetExternalMetric` / `FailedGetObjectMetric` (проблемы с Prometheus Adapter / KEDA), и `Reason` `InvalidMetricType` (несовместимая схема метрики).

### Шаг 2: Проверка конвейера метрик

HPA запрашивает данные через Aggregated API.

1. **Базовые метрики (CPU/Memory):**
   ```bash
   # Проверка доступности Metrics API
   kubectl get apiservice v1beta1.metrics.k8s.io
   # Проверка данных
   kubectl top pods
   ```
2. **Кастомные/Внешние метрики (Prometheus, KEDA):**
   ```bash
   # Проверка регистрации API
   kubectl get apiservice | grep custom.metrics
   # Ручной запрос сырых данных метрик
   kubectl get --raw "/apis/custom.metrics.k8s.io/v1beta1" | jq .
   ```

### Шаг 3: Проверка спецификации Pod (Resources Requests)

**Если у контейнера не задан `resources.requests.cpu` (или memory), HPA не сможет рассчитать процент утилизации.**
- HPA рассчитывает: `(текущее потребление / request) * 100%`.
- Если `request` отсутствует, формула выдает ошибку, и вы видите `<unknown> / 70%`.

### Шаг 4: Проверка логики и лимитов

1. **Толерантность (Tolerance):** По умолчанию HPA не реагирует, если изменение метрики составляет менее 10% (0.1).
2. **Ready Pods:** HPA учитывает только поды в состоянии `Ready`. Если поды долго стартуют или падают (CrashLoop), расчеты будут неточными.
3. **Cluster Autoscaler:** Если HPA увеличил `desiredReplicas`, но поды в `Pending` — проверяйте наличие свободных ресурсов на узлах и работу Cluster Autoscaler.

## Основные концепции

### Архитектура и поток данных

```
cgroups → kubelet (cAdvisor) → Metrics Server (или Prometheus Adapter) → Aggregated API → HPA Controller → /scale subresource → Deployment/StatefulSet
```

Подробное описание каждого звена, форматов `MetricsAPI` и точек принятия решений см. в специализированном материале — [HPA: Основные концепции](../../Autoscaling/HPA/hpa_concepts.md) (архитектурный справочник).

### Формула расчёта desiredReplicas (HPA v2)

| Тип метрики | Формула | Источник | Пример |
|:---|:---|:---|:---|
| `Resource` (CPU/Memory) | `ceil[replicas × (currentUtilization / targetUtilization)]` | `metrics.k8s.io` | 3 реплики × (80% / 50%) = 5 |
| `ContainerResource` (v2) | Сумма/среднее по указанному контейнеру | `metrics.k8s.io` | Игнорирует sidecar с `requests: 0` |
| `Pod` (custom) | `ceil[replicas × (currentPodMetric / targetPodMetric)]` | `custom.metrics.k8s.io` | RPS: 1000 / 200 = 5 |
| `Object` (Deployment) | Аналогично, по объекту k8s | `custom.metrics.k8s.io` | Ingress RPS на Ingress-объекте |
| `External` (cluster-external) | Аналогично, по внешней сущности | `external.metrics.k8s.io` | RabbitMQ queue depth, Kafka lag |

Подробнее о `ContainerResource` (введено в `autoscaling/v2`, k8s 1.20+) и стратегиях выбора типа метрики — [HPA: Продвинутая настройка](../../Autoscaling/HPA/hpa_advanced.md).

### Настройка sync period и tolerance (флаги kube-controller-manager)

| Параметр | Дефолт | Назначение | Когда менять |
|:---|:---|:---|:---|
| `--horizontal-pod-autoscaler-sync-period` | `15s` | Как часто HPA Controller выполняет итерацию | Слишком часто (5-10s) — нагрузка на API Server; слишком редко (60s) — медленная реакция на всплески |
| `--horizontal-pod-autoscaler-tolerance` | `0.1` | Минимальное относительное изменение, на которое реагирует HPA | На высоконагруженных кластерах с сотнями HPA — увеличить до `0.2-0.3` для снижения churn |
| `--horizontal-pod-autoscaler-cpu-initalization-period` | `5m` | Сколько ждать после старта Pod'а, прежде чем учитывать его CPU | Для медленно стартующих JVM-приложений увеличить до `10-15m`, иначе HPA увидит «ложный» пик при warmup |
| `--horizontal-pod-autoscaler-downscale-stabilization` | `5m` | Окно стабилизации scaleDown (default в `behavior.scaleDown.stabilizationWindowSeconds`) | При flaky-нагрузке (ночные batch-ы, cron) — увеличить до `10-15m` |
| `--horizontal-pod-autoscaler-upscale-stabilization` | `0s` | Окно стабилизации scaleUp (default) | Если HPA реагирует на короткие всплески — увеличить до `30-60s` |

> На управляемых кластерах (RKE2, kubeadm) эти флаги задаются в `/etc/kubernetes/manifests/kube-controller-manager.yaml` (control-plane static pod) или через Helm-чарт `kube-prometheus-stack` / `cluster-autoscaler` values.

### kube-state-metrics как источник состояния HPA

`kube-state-metrics` экспортирует метрики HPA в формате Prometheus:

| Метрика | Тип | Что показывает |
|:---|:---|:---|
| `kube_horizontalpodautoscaler_status_current_replicas` | Gauge | Текущее `status.currentReplicas` |
| `kube_horizontalpodautoscaler_status_desired_replicas` | Gauge | `status.desiredReplicas` |
| `kube_horizontalpodautoscaler_spec_max_replicas` | Gauge | `spec.maxReplicas` |
| `kube_horizontalpodautoscaler_spec_min_replicas` | Gauge | `spec.minReplicas` |
| `kube_horizontalpodautoscaler_status_condition` | Gauge (0/1 по `condition`, `status`) | Состояния `AbleToScale`, `ScalingActive`, `ScalingLimited` |
| `kube_horizontalpodautoscaler_metadata_generation` | Gauge | Версия спецификации (полезно для отслеживания drift'а) |

> В отличие от `metrics-server` (Aggregated API для HPA в реальном времени), `kube-state-metrics` показывает **декларативное состояние** HPA-объекта и его `status`. Используется для дашбордов и алертов, **не** для расчёта replicas.

### Поведение (behavior) и политики масштабирования

HPA v2 (`autoscaling/v2`) позволяет задать **раздельные политики** для scaleUp и scaleDown:

```yaml
behavior:
  scaleUp:
    stabilizationWindowSeconds: 0        # scaleUp — по умолчанию 0
    policies:
    - type: Percent
      value: 100                         # удваивать за период
      periodSeconds: 30
    - type: Pods
      value: 4                           # или +4 пода за период
      periodSeconds: 30
    selectPolicy: Max                    # выбрать то, что даст больше реплик
  scaleDown:
    stabilizationWindowSeconds: 300      # ждать 5 минут перед scaleDown
    policies:
    - type: Percent
      value: 10                          # удалять не более 10% за период
      periodSeconds: 60
    selectPolicy: Min                    # выбрать то, что даст меньшее удаление
```

**Правило выбора policy**: `selectPolicy: Max` для scaleUp (агрессивный рост), `selectPolicy: Min` для scaleDown (консервативное уменьшение). Подробный разбор `behavior` и `selectPolicy` — [HPA: Продвинутая настройка](../../Autoscaling/HPA/hpa_advanced.md).

### Масштабирование StatefulSet (особенности)

StatefulSet масштабируется HPA с момента, когда в `spec.template.spec` указан `replicas`. Но:

- **Стабильные identity**: при scaleDown HPA удаляет поды в порядке `Ordinal: N-1, N-2, …` (от большего к меньшему). PersistentVolumeClaim `data-myapp-N` удаляется только если `spec.persistentVolumeClaimRetentionPolicy.whenScaled: Delete` (по умолчанию `Retain`).
- **Headless Service**: StatefulSet требует headless Service (`clusterIP: None`). HPA изменяет только `replicas`, не service.
- **Расчёт метрик**: если метрика — RPS, для StatefulSet часто считают per-pod (например, KEDA scaler `lag` на Kafka consumer group).
- **Расширение сверх `minAvailable` PDB**: HPA может попытаться удалить под под PDB; PDB заблокирует `eviction`, но не `scaleDown` (PDB не блокирует HPA, но VPA/узловой drain блокирует). Подробнее — [Сценарий 6](#сценарий-6-конфликт-hpa-и-poddisruptionbudget-pdb).

### Отладка через events и логи

```bash
# События HPA за последние 30 минут
kubectl get events --field-source horizontal-pod-autoscaler -A --sort-by='.lastTimestamp' | tail -20

# События целевого объекта
kubectl describe deploy/<name> | grep -A 20 Events

# Логи контроллера HPA (control-plane)
kubectl logs -n kube-system kube-controller-manager-<node> | grep -i "horizontal\|hpa\|scaling" | tail -30

# Метрики API Server (если включены)
kube-apiserver --request-timeout=60s
# → метрика apiserver_request_duration_seconds{resource="horizontalpodautoscalers"}
```

Признаки неисправности в events: `FailedComputeMetricsReplicas`, `FailedGetScale` (часто RBAC), `FailedGetResourceMetric` (Metrics API), `ScaledUpError` (Quota превышен).

## Практические сценарии

### Сценарий 1: Статус <unknown> при работающем metrics-server
- **Проблема:** `kubectl top pods` показывает данные, но HPA пишет `<unknown>`.
- **Причина:** В Deployment несколько контейнеров (например, sidecar), и у одного из них не указаны `requests`. HPA требует `requests` для **всех** контейнеров пода, если используется тип метрики `Resource`.
- **Решение:** Укажите `requests` для всех контейнеров или используйте `ContainerResource` (v2 API) для масштабирования только по основному контейнеру.
- **Расширенная диагностика:**
  ```bash
  # 1. Подтвердить, что metrics-server видит под
  kubectl top pods -l app=<name> --containers
  # → container cpu: 50m  memory: 256Mi
  
  # 2. Проверить, есть ли HPA per-container
  kubectl get hpa <hpa> -o jsonpath='{.spec.metrics[*].type}'
  # → Resource, Resource (если v1) или ContainerResource (если v2)
  
  # 3. Проверить requests всех контейнеров
  kubectl get deploy/<name> -o json | jq '.spec.template.spec.containers[] | {name, requests}'
  # → name: "app"     requests: {"cpu":"100m"}
  # → name: "istio-proxy" requests: {}     ← ПРОБЛЕМА
  ```
- **Если sidecar — `istio-proxy` / `linkerd-proxy` / `vault-agent`**, добавьте явный `requests` (например, `cpu: 10m, memory: 64Mi`). Альтернативно — переход на `ContainerResource` с указанием имени основного контейнера.

### Сценарий 2: HPA не масштабирует вниз (Scale Down)
- **Причина 1 (Behavior):** По умолчанию окно стабилизации для scaleDown составляет **300 секунд (5 минут)**. HPA ждет подтверждения стабильности низкой нагрузки.
- **Причина 2 (Memory):** Приложение (особенно Java/Go) не возвращает память ОС после Garbage Collection. Метрика `working_set_bytes` остается высокой, и HPA «видит» нагрузку.
- **Причина 3 (ArgoCD):** Если в Git указано `replicas: 3` и включен `selfHeal`, ArgoCD будет мгновенно возвращать количество реплик назад, конфликтуя с HPA.
- **Решение:** Настройте `behavior.scaleDown.stabilizationWindowSeconds` или добавьте `ignoreDifferences` в ArgoCD.
- **Расширенная причина 4 (GitOps Controller race):** Flux, ArgoCD, Fleet работают по принципу «spec → status» через `kubectl apply`. HPA изменяет только `spec.replicas` через `/scale` subresource, но если GitOps контроллер перезаписывает весь `spec`, он может перезатереть изменения HPA. Решение: `ignoreDifferences` на поле `spec.replicas` (ArgoCD) или `replicaSets` reconcile-annotation (Flux).

### Сценарий 3: Дребезг (Flapping)
- **Симптом:** Поды создаются и удаляются каждые пару минут.
- **Причина:** Слишком узкий диапазон реплик или отсутствие окна стабилизации при резких всплесках трафика.
- **Решение:** Настройте политики в секции `behavior`:
```yaml
behavior:
  scaleDown:
    stabilizationWindowSeconds: 600 # Увеличить до 10 минут
    policies:
    - type: Percent
      value: 10
      periodSeconds: 60 # Удалять не более 10% в минуту
```
- **Расширенная диагностика:**
  ```bash
  # История изменений replicas за последний час
  kubectl get hpa <name> -o jsonpath='{.status}' | jq .
  
  # Скорость создания/удаления подов (events)
  kubectl get events --field-source horizontal-pod-autoscaler -A \
    | grep -E "ScaledUp|ScaledDown" | tail -20
  ```
- **Альтернативное решение — увеличить `tolerance`** в kube-controller-manager:
  ```bash
  kube-controller-manager --horizontal-pod-autoscaler-tolerance=0.2
  ```
  При `tolerance=0.2` HPA игнорирует изменения метрики < 20%, что снижает churn на нагруженных системах.

### Сценарий 4: Конфликт HPA и VPA
- **Проблема:** Бесконечный цикл изменения количества подов и их ресурсов.
- **Причина:** Использование HPA и VPA на одной и той же метрике (CPU/Memory).
- **Решение:** Используйте VPA только в режиме `Off` (для рекомендаций) или разделите метрики: HPA по RPS (через KEDA/Prometheus), VPA по CPU/Memory.
- **Подводный камень:** VPA в режиме `Auto` перезаписывает `resources.requests` в Pod spec, что ломает HPA-расчёт `currentUtilization / request` (если request изменился, HPA увидит скачок). Решение — использовать VPA в режиме `Initial` (только при создании Pod) или `Off` (только рекомендации через CRD `VerticalPodAutoscalerRecommender`).

### Сценарий 5: KEDA scaler возвращает нечисловое значение (NaN)
- **Проблема:** HPA при `KEDA` ScaledObject показывает `<unknown>` или `0/0`, хотя KEDA-адаптер (`keda-operator-metrics-apiserver`) зарегистрирован.
- **Причина:** Источник метрики (RabbitMQ queue depth, Kafka lag, Redis list length) возвращает нечисловое значение (например, `NaN` или строку `null`) из-за сетевого сбоя или auth-ошибки.
- **Решение:**
  ```bash
  # 1. Проверить ScaledObject status
  kubectl get so <name> -o jsonpath='{.status}' | jq .
  # → условие Ready: True/False, Active/MetricName
  
  # 2. Проверить сырое значение метрики (в External Metrics API)
  kubectl get --raw "/apis/external.metrics.k8s.io/v1beta1" | jq .
  # → должно быть числовое значение
  
  # 3. Логи KEDA-оператора
  kubectl logs -n keda deploy/keda-operator | grep -i "<name>\|<trigger>"
  ```
- **Альтернативная причина — Paused ScaledObject**: KEDA ставит ScaledObject в `Paused` если не удаётся получить метрику 3+ раза подряд. Проверить: `kubectl get so <name> -o jsonpath='{.status.paused}'`.
- **Связь с HPA**: KEDA создаёт «теневой» HPA (`keda-hpa-<name>`) в namespace HPA-объекта. Удалять его вручную нельзя — KEDA управляет им. Для on-prem KEDA с Prometheus trigger — `serverAddress` должен быть доступен с control-plane Pod'а KEDA.

### Сценарий 6: Конфликт HPA и PodDisruptionBudget (PDB)
- **Проблема:** При `kubectl drain` узла PDB блокирует eviction, но HPA успешно уменьшает `replicas`. После `drain` оказывается, что часть подов не может быть пересоздана.
- **Причина:** HPA **не учитывает PDB** при scaleDown (PDB влияет только на eviction). Поэтому HPA может уменьшить `replicas` ниже `minAvailable` из PDB, и поды будут удалены без блокировки.
- **Решение:**
  1. Задать `minReplicas` в HPA с учётом PDB:
     ```yaml
     spec:
       minReplicas: 3  # = или > PDB.minAvailable
     ```
  2. Использовать VPA + PDB в режиме `updateMode: Initial` (VPA не меняет `replicas`, только `requests`).
  3. Настроить `kube-controller-manager` флаг `--pod-eviction-timeout` (default 5 минут) для согласованности с PDB.
- **Пример неправильной конфигурации:**
  ```yaml
  # PDB: minAvailable=2 (при 5 репликах)
  # HPA: minReplicas=1, maxReplicas=10
  # → HPA может уменьшить до 1 пода, нарушив PDB intent
  ```

### Сценарий 7: HPA увеличивает поды, но они в Pending (race с Cluster Autoscaler)
- **Симптом:** `kubectl get hpa` показывает `desiredReplicas: 20`, `currentReplicas: 20`, но 8 подов в `Pending`. Cluster Autoscaler не успевает добавить узлы.
- **Причина:** При резком скачке метрики HPA за один цикл удваивает реплики (`behavior.scaleUp.policies.percent=100`). CA требует времени на provision (cloud) или bring-up (on-prem, 3-7 минут).
- **Решение:**
  1. **Снизить агрессивность scaleUp**:
     ```yaml
     behavior:
       scaleUp:
         policies:
         - type: Pods
           value: 4           # максимум +4 пода за 30 сек
           periodSeconds: 30
     ```
  2. **Добавить startup stabilization** — `kube-controller-manager --horizontal-pod-autoscaler-upscale-stabilization=30s` (HPA не реагирует на короткие всплески).
  3. **Увеличить `cpu-initialization-period`** для медленных приложений:
     ```bash
     kube-controller-manager --horizontal-pod-autoscaler-cpu-initialization-period=10m
     ```
  4. **Предварительный прогрев** (predictive scaling) — HPA не имеет built-in predictive scaling; используйте KEDA `cron` scaler или внешний cron-контроллер (например, `predictive-horizontal-pod-autoscaler` от Google) для планового добавления реплик перед известной нагрузкой.
- **Диагностика:**
  ```bash
  # CA events
  kubectl get events -n kube-system | grep cluster-autoscaler | tail -20
  # HPA events (ScaledUp до CA add node)
  kubectl get events --field-source horizontal-pod-autoscaler | tail -10
  ```

### Сценарий 8: HPA не реагирует на скачок из-за initContainer warmup
- **Симптом:** HPA показывает стабильные 70% CPU, хотя приложение явно «захлёбывается». Или наоборот: HPA резко увеличивает реплики при cold start.
- **Причина:** Init-контейнеры (`spec.initContainers`) потребляют ресурсы в момент старта Pod'а. HPA видит это как «всплеск» метрики, хотя основной контейнер ещё не запущен. С k8s 1.20+ initContainer requests **учитываются** при scheduling, но не для HPA-расчёта (HPA использует только `containers[].resources.requests`).
- **Решение:**
  1. Установить `kube-controller-manager --horizontal-pod-autoscaler-cpu-initialization-period=5m` (default) или больше для долгих init-контейнеров (миграции БД, прогрев JVM).
  2. Перенести тяжёлую инициализацию в `startupProbe` основного контейнера, а не в init.
  3. Для HPA по memory: в Java/Go приложениях метрика включает heap до GC, что искажает картину в первые минуты. Решение — JMX-exporter с метрикой `jvm_memory_bytes_used` (после GC) вместо cAdvisor `memory.working_set`.

### Сценарий 9: HPA vs AntiAffinity / TopologySpreadConstraints (масштабирование блокируется)
- **Симптом:** HPA запрашивает 10 реплик, но scheduler размещает только 5 — остальные в `Pending` с событием `0/6 nodes are available: 6 node(s) didn't match Pod's anti-affinity rules`.
- **Причина:** Жёсткий `podAntiAffinity` (без `preferredDuringScheduling`) не даёт разместить более 1 пода на узел. Если узлов < `desiredReplicas` — поды «зависают».
- **Решение:**
  1. Использовать `preferredDuringSchedulingIgnoredDuringExecution` вместо `required` (мягкая anti-affinity):
     ```yaml
     podAntiAffinity:
       preferredDuringSchedulingIgnoredDuringExecution:
       - weight: 100
         podAffinityTerm:
           labelSelector: {matchLabels: {app: my-app}}
           topologyKey: kubernetes.io/hostname
     ```
  2. Использовать `topologySpreadConstraints` с `maxSkew: 1` и `whenUnsatisfiable: ScheduleAnyway`.
  3. Увеличить количество узлов через Cluster Autoscaler с правильным `expander: least-waste` или `priority` (для on-prem — `cluster-api`/`cabpr` controller).
- **Диагностика:**
  ```bash
  kubectl describe pod <pending-pod> | grep -A 5 "Events:"
  # → 0/6 nodes are available: 6 node(s) didn't match Pod's anti-affinity rules
  ```

### Сценарий 10: HPA реагирует на метрику, которая не отражает реальную нагрузку
- **Проблема:** CPU загружен на 30% (HPA «спит»), но latency p99 = 2 сек (пользователи жалуются).
- **Причина:** HPA масштабирует по CPU/Memory, но приложение latency-bound (база данных, внешний API) или I/O-bound (Kafka consumer, RabbitMQ consumer).
- **Решение:**
  1. **Latency-based scaling** (через Prometheus Adapter):
     ```yaml
     metrics:
     - type: Pods
       pods:
         metric:
           name: http_request_duration_seconds_p99
         target:
           type: AverageValue
           averageValue: "0.5"  # p99 < 500ms
     ```
  2. **Queue-length scaling** (KEDA + Kafka/RabbitMQ):
     ```yaml
     triggers:
     - type: kafka
       metadata:
         bootstrapServers: kafka.svc:9092
         consumerGroup: my-group
         lagThreshold: "100"  # масштабировать, если lag > 100
     ```
  3. **RPS-based scaling** (через Istio/Envoy metrics):
     ```yaml
     - type: Object
       object:
         describedObject: {kind: Service, name: my-app}
         metric: {name: istio_requests_per_second}
         target: {type: Value, value: "1000"}
     ```
- **Золотое правило**: метрика HPA должна быть **leading indicator** (латентность, очередь, RPS), а не **lagging** (CPU, memory). CPU/Memory — fallback, когда нет бизнес-метрик.

## Дополнительная информация

### Чек-лист диагностики HPA (от простого к сложному)

| # | Команда / действие | Что проверяет | Ожидаемый результат |
|:---|:---|:---|:---|
| 1 | `kubectl get hpa -A` | Состояние всех HPA | Все `READY: True`, `TARGETS` заполнены (не `<unknown>/N%`) |
| 2 | `kubectl describe hpa <name>` | Conditions, Events | `AbleToScale=True`, `ScalingActive=True`, `ScalingLimited=False` |
| 3 | `kubectl top pods -l app=<name> --containers` | Metrics Server данные | Реальные значения CPU/memory |
| 4 | `kubectl get apiservice \| grep -E "metrics\|custom\|external"` | Регистрация API-сервисов | Все `AVAILABLE: True` |
| 5 | `kubectl get --raw "/apis/metrics.k8s.io/v1beta1/pods" \| jq '.items \| length'` | Количество подов с метриками | > 0 в healthy-кластере |
| 6 | `kubectl get events --field-source horizontal-pod-autoscaler -A --sort-by='.lastTimestamp' \| tail -20` | Последние события HPA | Нет `Failed*` событий в норме |
| 7 | `kubectl get deploy/<name> -o json \| jq '.spec.template.spec.containers[].resources.requests'` | requests у всех контейнеров | Не пусто, ни у одного контейнера |
| 8 | `kubectl get hpa <name> -o yaml \| yq '.spec.behavior'` | Наличие behavior | Либо отсутствует, либо с явной `stabilizationWindowSeconds` |
| 9 | `kubectl get pdb -A` | PDB конфликты | `minAvailable` ≤ HPA `minReplicas` |
| 10 | `kubectl get events -n kube-system \| grep cluster-autoscaler \| tail -10` | CA-активность | Нет `FailedToScale` при `Pending`-подах |
| 11 | `kubectl get so -A` (если KEDA) | ScaledObject статус | Все `READY: True`, нет `PAUSED` |
| 12 | `kubectl get --raw "/apis/external.metrics.k8s.io/v1beta1" \| jq .` | Внешние метрики | Записи для используемых ScaledObject |

### Типичные антипаттерны HPA-конфигурации

| Антипаттерн | Симптом | Корректная практика |
|:---|:---|:---|
| HPA по CPU, но приложение latency-bound (БД, API) | HPA «спит», пользователи жалуются | HPA по latency p99 (Prometheus Adapter) или queue lag (KEDA) |
| `minReplicas: 1` в production | При scaleDown → 0 → холодный старт следующего запроса | `minReplicas >= 2` для HA, или `minReplicas = ceil(requests * N)` |
| Отсутствует `resources.requests` у sidecar (istio, vault) | `<unknown>` в HPA TARGETS | Добавить явные requests (например, 10m CPU, 64Mi mem) |
| `behavior.scaleUp.percent: 1000` за 15 секунд | Резкий spike → CA не успевает | Ограничить `Pods: 4` за 30 сек + снизить `sync-period` |
| `behavior.scaleDown.stabilizationWindowSeconds: 0` | Дребезг на коротких спадах нагрузки | `scaleDown.stabilizationWindowSeconds: 300+` |
| VPA `Auto` + HPA на той же Deployment | Конфликт при каждом reconcile | VPA в `Off`/`Initial` или HPA по внешней метрике, VPA по CPU |
| HPA + ArgoCD `selfHeal: true` без `ignoreDifferences` | ArgoCD мгновенно откатывает `replicas` после HPA | ArgoCD `ignoreDifferences: jsonPointers: [/spec/replicas]` |
| HPA на Pod (без Deployment) через `scaleTargetRef` | Не работает: HPA требует controller с subresource `/scale` | Использовать `Deployment`, `StatefulSet` или `ReplicaSet` |
| `maxReplicas` значительно больше, чем позволяет кластер | Поды в `Pending` → HPA не знает об этом | `maxReplicas <= ceil(sum_node_capacity / pod_request)` |
| `metrics-server` с `metric-resolution: 30s` + `sync-period: 15s` | HPA видит устаревшие данные | `metric-resolution <= sync-period` (иначе HPA «ждёт» метрики) |
| HPA по `memory` для Java/Go без warmup | Ложные срабатывания при cold start | `cpu-initialization-period: 10m` или HPA по CPU/latency |
| HPA + PDB `minAvailable: 1` при HPA `minReplicas: 1` | При drain PDB ничего не блокирует (только 1 под) | `minAvailable = ceil(replicas * 0.7)` для HA |

### Готовые Prometheus-алерты для HPA (для on-prem kube-prometheus-stack)

```yaml
groups:
- name: hpa.rules
  rules:
  - alert: HpaUnableToScale
    expr: kube_horizontalpodautoscaler_status_condition{condition="AbleToScale",status="false"} == 1
    for: 10m
    labels: {severity: warning}
    annotations:
      summary: "HPA {{ $labels.horizontalpodautoscaler }} не может масштабировать"
      description: "HPA в namespace {{ $labels.namespace }} не может изменить replicas целевого объекта. Проверьте RBAC и существование целевого объекта."

  - alert: HpaMetricsUnavailable
    expr: kube_horizontalpodautoscaler_status_condition{condition="ScalingActive",status="false"} == 1
    for: 5m
    labels: {severity: critical}
    annotations:
      summary: "HPA {{ $labels.horizontalpodautoscaler }} не получает метрики"
      description: "Метрики недоступны более 5 минут. Проверьте metrics-server / Prometheus Adapter / KEDA."

  - alert: HpaAtMaxReplicas
    expr: kube_horizontalpodautoscaler_status_condition{condition="ScalingLimited",status="true"} == 1
    for: 15m
    labels: {severity: warning}
    annotations:
      summary: "HPA {{ $labels.horizontalpodautoscaler }} уперся в maxReplicas"
      description: "Нагрузка выше maxReplicas в течение 15+ минут. Возможно, нужно увеличить maxReplicas или оптимизировать приложение."

  - alert: HpaDesiredVsCurrentMismatch
    expr: kube_horizontalpodautoscaler_status_desired_replicas != kube_horizontalpodautoscaler_status_current_replicas
    for: 10m
    labels: {severity: info}
    annotations:
      summary: "HPA {{ $labels.horizontalpodautoscaler }} не может достичь desiredReplicas"
      description: "desiredReplicas={{ $value }} != currentReplicas. Проверьте PDB, квоты, ресурсы кластера."

  - alert: HpaFlapping
    expr: |
      changes(kube_horizontalpodautoscaler_status_current_replicas[10m]) > 6
    for: 5m
    labels: {severity: warning}
    annotations:
      summary: "HPA {{ $labels.horizontalpodautoscaler }} flapping"
      description: "replicas изменилось более 6 раз за 10 минут. Увеличьте stabilizationWindowSeconds или tolerance."
```

### PromQL-запросы для дашбордов HPA (Grafana)

Полезные метрики и запросы для построения дашборда мониторинга HPA:

**1. Текущее vs желаемое количество реплик:**
```promql
# Разрыв между текущим и целевым
kube_horizontalpodautoscaler_status_current_replicas
  - kube_horizontalpodautoscaler_status_desired_replicas
```

**2. Процент использования maxReplicas:**
```promql
# Насколько HPA близок к лимиту (0-100%)
kube_horizontalpodautoscaler_status_current_replicas
  / kube_horizontalpodautoscaler_spec_max_replicas * 100
```

**3. История масштабирования:**
```promql
# Количество изменений replicas за 10 минут
changes(kube_horizontalpodautoscaler_status_current_replicas[10m])
```

**4. Статус условий HPA:**
```promql
# HPA не может масштабировать (AbleToScale=False)
kube_horizontalpodautoscaler_status_condition{
  condition="AbleToScale",status="false"
}

# Метрики недоступны (ScalingActive=False)
kube_horizontalpodautoscaler_status_condition{
  condition="ScalingActive",status="false"
}

# Достигнут лимит (ScalingLimited=True)
kube_horizontalpodautoscaler_status_condition{
  condition="ScalingLimited",status="true"
}
```

**5. Отношение CPU usage к requests (для HPA по CPU):**
```promql
# Средняя утилизация CPU относительно requests
sum(rate(container_cpu_usage_seconds_total{
  namespace="$namespace", pod=~"$pod.*"
}[5m])) by (pod)
/
sum(kube_pod_container_resource_requests{
  namespace="$namespace", pod=~"$pod.*", resource="cpu"
}) by (pod) * 100
```

**6. Latency P99 (для HPA по latency):**
```promql
# P99 latency по сервису
histogram_quantile(0.99,
  sum(rate(http_request_duration_seconds_bucket{
    namespace="$namespace", service="$service"
  }[5m])) by (le)
)
```

**7. RPS по подам (для HPA по RPS):**
```promql
# Requests per second на каждый под
sum(rate(http_requests_total{
  namespace="$namespace", pod=~"$pod.*"
}[2m])) by (pod)
```

**8. Ошибки HPA:**
```promql
# Количество Failed* событий
sum(kube_horizontalpodautoscaler_status_condition{
  condition=~"ScalingActive|AbleToScale", status="false"
}) by (horizontalpodautoscaler, namespace, condition)
```

**Пример Grafana-панели:**
```json
{
  "title": "HPA: Replicas Current vs Desired",
  "targets": [
    {
      "expr": "kube_horizontalpodautoscaler_status_current_replicas{namespace=\"$namespace\"}",
      "legendFormat": "{{horizontalpodautoscaler}} current"
    },
    {
      "expr": "kube_horizontalpodautoscaler_status_desired_replicas{namespace=\"$namespace\"}",
      "legendFormat": "{{horizontalpodautoscaler}} desired"
    },
    {
      "expr": "kube_horizontalpodautoscaler_spec_max_replicas{namespace=\"$namespace\"}",
      "legendFormat": "{{horizontalpodautoscaler}} max"
    }
  ]
}
```

### Совет для собеседования

**Вопрос:** Почему HPA может показывать `<unknown>`?
**Ответ:** Я проверю три фактора:
1. **Инфраструктура:** Работает ли `metrics-server` и зарегистрирован ли API Service.
2. **Манифест:** Указаны ли `resources.requests` для **всех** контейнеров в поде.
3. **Сеть/RBAC:** Имеет ли контроллер HPA доступ к эндпоинту метрик (проверка логов `kube-controller-manager`).

> Дополнительные вопросы на интервью по HPA (KEDA vs HPA, behavior, PDB conflict, GitOps race) — [HPA: Основные концепции](../../Autoscaling/HPA/index.md).

### Связанные темы

- [HPA: Основные концепции](../../Autoscaling/HPA/hpa_concepts.md) — архитектура, control loop, формула расчёта, типы метрик (Resource, ContainerResource, Pod, Object, External).
- [HPA: Продвинутая настройка](../../Autoscaling/HPA/hpa_advanced.md) — подробный разбор `behavior.scaleUp/scaleDown`, `selectPolicy`, `ContainerResource`, predictive scaling.
- [Cluster Autoscaler (детально)](../../Autoscaling/cluster_autoscaler_detailed.md) — взаимодействие HPA ↔ CA, race conditions при provision узлов, PDB + drain.
