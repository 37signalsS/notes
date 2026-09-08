# Вертикальное авто-масштабирование подов (Vertical Pod Autoscaler — VPA)

## Определения

**Vertical Pod Autoscaler (VPA)** — механизм Kubernetes для автоматического управления ресурсами контейнеров (`requests` и `limits` CPU и памяти) на основе анализа истории их реального потребления. В отличие от HPA, который изменяет количество реплик, VPA оптимизирует «размер» самих подов.

**In-Place Pod Resize** — технология (GA с версии 1.35), позволяющая изменять ресурсы запущенного контейнера без перезапуска пода. VPA активно использует этот механизм для минимизации простоев.

**Overprovisioning** — выделение ресурсов сверх реальной необходимости, что ведет к неэффективному использованию кластера и росту затрат.

**Underprovisioning** — нехватка ресурсов, приводящая к троттлингу (CPU throttling) или аварийному завершению (OOMKilled).

**VPA Recommendation** — набор расчетных значений (Target, LowerBound, UpperBound), генерируемых компонентом Recommender для конкретной рабочей нагрузки.

**Recommender** — компонент VPA, который опрашивает Metrics Server, агрегирует историю потребления и вычисляет оптимальные значения ресурсов.

**Updater** — компонент VPA, который отслеживает отклонения фактического потребления от границ рекомендаций и инициирует применение новых ресурсов.

**Admission Controller (VPA Admission)** — мутирующий вебхук, который подставляет рекомендованные значения `requests`/`limits` в спецификацию пода в момент его создания.

**uncappedTarget** — рекомендация, рассчитанная Recommender без учета ограничений `minAllowed`/`maxAllowed`. Полезна для выявления скрытого дефицита ресурсов.

**controlledValues** — параметр VPA, определяющий, какие поля ресурсов изменять: только `Requests`, только `Limits` или оба сразу (`RequestsAndLimits`).

---

## Предварительные требования

### Требования к кластеру

- **Kubernetes:** версия 1.27+ (Beta In-Place Resize), 1.35+ (GA In-Place Resize)
- **Kubelet:** флаги `--kube-reserved` и `--system-reserved` настроены для корректного расчета `Node Allocatable`
- **Container Runtime:** containerd 1.7+ или CRI-O 1.26+ с поддержкой cgroups v2
- **Cgroup v2:** обязателен для корректной работы изменения лимитов памяти без сбоев
- **Metrics Server:** установлен и функционирует (обязателен для Recommender)

### Инструменты

- **kubectl:** версия 1.27+
- **Helm:** версия 3.0+ (рекомендуется для установки VPA)
- **Prometheus + kube-state-metrics:** для мониторинга событий VPA и алертинга

### Проверка готовности

```bash
# Проверка версии Kubernetes
kubectl version --short
# → Client: v1.35.0
# → Server: v1.35.0

# Проверка Metrics Server
kubectl top nodes
# → NAME   CPU(cores)   CPU%   MEMORY(bytes)   MEMORY%
# → node1  250m         12%    2048Mi          51%

# Проверка cgroups версии
stat -fc %T /sys/fs/cgroup/
# → cgroup2fs

# Проверка наличия VPA компонентов
kubectl get pods -n kube-system -l app=vpa
# → NAME                             READY   STATUS
# → vpa-recommender-xxx              1/1     Running
# → vpa-updater-xxx                  1/1     Running
# → vpa-admission-controller-xxx     1/1     Running

# Проверка Admission Webhook
kubectl get validatingwebhookconfiguration vpa-webhook-config
# → NAME                WEBHOOKS   AGE
# → vpa-webhook-config  1          2d
```

### Начальное состояние

- Кластер запущен и доступен через `kubectl`
- Metrics Server установлен и возвращает метрики через `kubectl top`
- Имеется как минимум один рабочий узел (worker node)
- Пользователь имеет права на создание Deployment, StatefulSet, VPA в целевом Namespace

---

## Основные концепции

### Назначение и преимущества

1.  **Right-sizing:** Автоматическое приведение `requests` к значениям, максимально близким к реальному потреблению.
2.  **Защита от OOM:** Проактивное увеличение лимитов памяти при обнаружении признаков нехватки ресурсов.
3.  **Снижение операционных затрат:** Оптимизация лимитов позволяет Cluster Autoscaler и Karpenter более плотно упаковывать поды на узлах (bin packing).
4.  **Улучшение стабильности:** Предотвращение троттлинга CPU, который может приводить к росту задержек (latency).

### Архитектура и компоненты

VPA состоит из трех независимых компонентов, развернутых в кластере:

| Компонент | Техническая роль | Развертывание |
| :--- | :--- | :--- |
| **VPA Recommender** | Опрашивает Metrics Server, собирает историю (по умолчанию за 8 дней) и рассчитывает рекомендации. Использует экспоненциальное сглаживание. | Deployment |
| **VPA Updater** | Мониторит запущенные поды. Если ресурсы пода выходят за рамки `LowerBound`/`UpperBound`, инициирует обновление через In-Place Resize или перезапуск. | Deployment |
| **VPA Admission Controller** | Мутирующий вебхук, который подставляет рекомендованные значения ресурсов в спецификацию пода в момент его создания. | Deployment + ValidatingWebhookConfiguration |

### Поток данных (Data Flow)

```
Container (cgroups)
    ↓ (cAdvisor через Kubelet)
Metrics Server (Resource Metrics API)
    ↓ (HTTP polling каждые ~1min)
VPA Recommender → (хранит историю, считает перцентили)
    ↓ (обновляет CRD VerticalPodAutoscaler)
VPA Updater / Admission Controller
    ↓ (PATCH / Mutation)
Pod (spec.containers[].resources)
```

### Режимы работы (`updateMode`)

| Режим | Поведение | Сценарий использования |
| :--- | :--- | :--- |
| **`Off`** | Только расчет рекомендаций без применения. | Аудит ресурсов, подготовка к внедрению, критические БД. |
| **`Initial`** | Применение ресурсов только при создании пода. | Плавное внедрение, приложения с долгим прогревом. |
| **`Recreate`** | Всегда перезапускает под для применения новых ресурсов. | Устаревшие кластеры (< 1.35) или несовместимые приложения. |
| **`InPlaceOrRecreate`** | **Стандарт 2026 года**. Приоритетно использует In-Place Resize, при невозможности — перезапуск. | Большинство современных нагрузок. |
| **`InPlace`** | Только неразрушающее обновление. Если места на узле нет — ждет. | Тяжелые Stateful-приложения (Elasticsearch, Kafka). |

### controlledValues

Параметр определяет, какие поля ресурсов изменять:

- **`Requests`**: VPA изменяет только `requests`. Полезно, если `limits` заданы фиксированно.
- **`Limits`**: VPA изменяет только `limits`. Полезно для защиты от OOM без изменения планирования.
- **`RequestsAndLimits`**: VPA изменяет оба поля синхронно. Стандартный режим для полного right-sizing.

---

## Технический алгоритм и формулы

### Алгоритм Recommender

Recommender использует **95-й перцентиль** для CPU и **99-й перцентиль** для памяти.

1.  **Окно наблюдения:** По умолчанию анализируются данные за последние 8 дней (`--recommender-interval`).
2.  **Веса данных:** Используется экспоненциальный распад весов — недавние всплески нагрузки имеют больший вес, чем старые данные.
3.  **OOM-коррекция:** При получении события `OOMKilled`, VPA моментально устанавливает новую рекомендацию как `max(текущее_потребление, лимит) * 1.2`. Исторические данные при этом игнорируются для быстрого восстановления.
4.  **Min/Max Constraints:** Рекомендации всегда ограничиваются значениями из `resourcePolicy`.

### Секция статуса VPA

-   **`lowerBound`**: Порог, ниже которого VPA считает под критически недогруженным и инициирует обновление.
-   **`target`**: Целевое значение, к которому стремится VPA.
-   **`upperBound`**: Порог, выше которого под считается перегруженным (overprovisioned).
-   **`uncappedTarget`**: Рекомендация без учета ограничений `minAllowed`/`maxAllowed` в объекте VPA. Полезно для выявления скрытого дефицита.

### Взаимодействие с Kubernetes API

```bash
# Проверка статуса рекомендаций VPA
kubectl describe vpa my-app-vpa
```

Пример вывода:
```
Name:          my-app-vpa
Namespace:     default
Labels:        <none>
Annotations:   <none>
CreationTimestamp:  2026-01-15T10:00:00Z
Reference:          Deployment/my-app
Conditions:
  Type           Status  Reason
  ----           ------  ------
  RecommendationProvided   True   RecommenderProvided
Events:
  Type    Reason           Age   From           Message
  ----    ------           ----  ----           -------
  Normal  CalculationDone  2m    vpa-recommender  Recommendation generated successfully

Recommendation:
  Container Recommendations:
    Container Name:  app
    Lower Bound:     CPU: 50m, Memory: 128Mi
    Target:         CPU: 120m, Memory: 300Mi
    Upper Bound:     CPU: 500m, Memory: 1Gi
    Uncapped Target: CPU: 120m, Memory: 300Mi
```

---

## Практические сценарии

### Сценарий 1: Тонкая настройка политики (resourcePolicy)

Пример для приложения с сайдкаром, где мы хотим масштабировать только основной контейнер.

```yaml
apiVersion: autoscaling.k8s.io/v1
kind: VerticalPodAutoscaler
metadata:
  name: api-vpa
spec:
  targetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: my-api
  updatePolicy:
    updateMode: "InPlaceOrRecreate"
  resourcePolicy:
    containerPolicies:
      - containerName: "app"
        minAllowed:
          cpu: 250m
          memory: 512Mi
        maxAllowed:
          cpu: "4"
          memory: "8Gi"
        controlledValues: RequestsAndLimits
      - containerName: "istio-proxy"
        # Сайдкары обычно имеют предсказуемое потребление
        mode: "Off"
```

### Сценарий 2: VPA + In-Place Resize для StatefulSet

Обеспечение стабильности базы данных без разрыва соединений при изменении ресурсов.

```yaml
apiVersion: autoscaling.k8s.io/v1
kind: VerticalPodAutoscaler
metadata:
  name: postgres-vpa
spec:
  targetRef:
    apiVersion: apps/v1
    kind: StatefulSet
    name: postgres
  updatePolicy:
    updateMode: "InPlace" # Только без перезапуска
```

### Сценарий 3: Использование Goldilocks для визуализации

Goldilocks использует VPA в режиме `Off` для создания удобного Dashboard с рекомендациями.

1.  Установите VPA в кластер.
2.  Установите Goldilocks.
3.  Добавьте лейбл на Namespace: `kubectl label ns my-app goldilocks.fairwinds.com/enabled=true`.
4.  Откройте Dashboard для просмотра рекомендаций по всем подам в Namespace.

### Сценарий 4: VPA + HPA по разным метрикам

Корректная комбинация вертикального и горизонтального масштабирования без конфликтов.

```yaml
# VPA — только для right-sizing ресурсов
apiVersion: autoscaling.k8s.io/v1
kind: VerticalPodAutoscaler
metadata:
  name: api-vpa
spec:
  targetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: my-api
  updatePolicy:
    updateMode: "Off" # Только рекомендации, не применяем автоматически
  resourcePolicy:
    containerPolicies:
      - containerName: "app"
        controlledValues: RequestsAndLimits

---
# HPA — по RPS (кастомная метрика), не по CPU/Memory
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: api-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: my-api
  minReplicas: 2
  maxReplicas: 20
  metrics:
    - type: Pods
      pods:
        metric:
          name: http_requests_per_second
        target:
          type: AverageValue
          averageValue: "100"
  behavior:
    scaleUp:
      stabilizationWindowSeconds: 60
      policies:
        - type: Percent
          value: 100
          periodSeconds: 15
    scaleDown:
      stabilizationWindowSeconds: 300
      policies:
        - type: Percent
          value: 10
          periodSeconds: 60
```

### Сценарий 5: VPA + Cluster Autoscaler / Karpenter в On-prem окружении

Сценарий для кластера на bare metal, где при изменении ресурсов под может потребоваться переезд на узел с большей емкостью.

```yaml
# VPA с политикой, учитывающей ограничения узлов
apiVersion: autoscaling.k8s.io/v1
kind: VerticalPodAutoscaler
metadata:
  name: batch-worker-vpa
spec:
  targetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: batch-worker
  updatePolicy:
    updateMode: "InPlaceOrRecreate"
  resourcePolicy:
    containerPolicies:
      - containerName: "worker"
        minAllowed:
          cpu: 500m
          memory: "1Gi"
        maxAllowed:
          cpu: "4"
          memory: "16Gi"
        controlledValues: RequestsAndLimits
```

**Ожидаемое поведение:**
1.  VPARecommender вычисляет, что поду требуется `cpu: 2`, `memory: 8Gi`.
2.  VPAUpdater пытается применить In-Place Resize.
3.  Если на текущем узле нет 2 ядер и 8Gi свободной памяти (учитывая `requests` других подов), Kubelet возвращает `Infeasible`.
4.  VPAUpdater эвиктирует под (с учетом PDB).
5.  Cluster Autoscaler (или Karpenter) добавляет новый узел или перемещает под на узел с достаточной емкостью.

### Сценарий 6: VPA для StatefulSet с Pod Disruption Budget

Сценарий для баз данных, где необходимо ограничить количество одновременно перезапускаемых подов.

```yaml
# Pod Disruption Budget — защита от одновременного перезапуска всех реплик
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: postgres-pdb
spec:
  minAvailable: 2
  selector:
    matchLabels:
      app: postgres

---
# VPA для StatefulSet
apiVersion: autoscaling.k8s.io/v1
kind: VerticalPodAutoscaler
metadata:
  name: postgres-vpa
spec:
  targetRef:
    apiVersion: apps/v1
    kind: StatefulSet
    name: postgres
  updatePolicy:
    updateMode: "InPlaceOrRecreate"
  resourcePolicy:
    containerPolicies:
      - containerName: "postgres"
        minAllowed:
          cpu: 500m
          memory: "2Gi"
        maxAllowed:
          cpu: "4"
          memory: "16Gi"
        controlledValues: RequestsAndLimits
```

### Сценарий 7: Поэтапное внедрение VPA в Production

Стратегия внедрения с минимальным риском для работающей системы.

```bash
# Шаг 1: Установите VPA в режиме Off для всего namespace
kubectl apply -f - <<EOF
apiVersion: autoscaling.k8s.io/v1
kind: VerticalPodAutoscaler
metadata:
  name: audit-vpa
spec:
  targetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: my-api
  updatePolicy:
    updateMode: "Off"
EOF

# Шаг 2: Соберите рекомендации в течение 24-48 часов
kubectl describe vpa audit-vpa

# Шаг 3: Проверьте рекомендации в тестовом окружении
# Примените рекомендации вручную к манифесту Deployment

# Шаг 4: Включите Initial mode для новых подов
kubectl patch vpa audit-vpa --type='merge' -p '{"spec":{"updatePolicy":{"updateMode":"Initial"}}}'

# Шаг 5: Мониторьте в течение недели
kubectl get events --field-selector involvedObject.name=audit-vpa

# Шаг 6: Переключитесь на InPlaceOrRecreate
kubectl patch vpa audit-vpa --type='merge' -p '{"spec":{"updatePolicy":{"updateMode":"InPlaceOrRecreate"}}}'
```

### Сценарий 8: VPA для приложений с нативными сайдкарами (Native Sidecars, K8s 1.29+)

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: app-with-sidecar
spec:
  template:
    spec:
      initContainers:
      - name: init
        image: init-image:latest
      containers:
      - name: app
        image: app-image:latest
        resources:
          requests:
            cpu: 100m
            memory: 256Mi
          limits:
            cpu: 500m
            memory: 512Mi
      - name: sidecar
        image: sidecar-image:latest
        resources:
          requests:
            cpu: 50m
            memory: 128Mi
          limits:
            cpu: 200m
            memory: 256Mi
---
apiVersion: autoscaling.k8s.io/v1
kind: VerticalPodAutoscaler
metadata:
  name: app-with-sidecar-vpa
spec:
  targetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: app-with-sidecar
  updatePolicy:
    updateMode: "InPlaceOrRecreate"
  resourcePolicy:
    containerPolicies:
      - containerName: "app"
        controlledValues: RequestsAndLimits
      - containerName: "sidecar"
        mode: "Off" # Исключаем сайдкар из авто-масштабирования
```

---

## Интеграция с компонентами Kubernetes

### VPA + HPA

Никогда не используйте оба по CPU/Memory одновременно.

**Правильно:**
- HPA по RPS + VPA по ресурсам (VPA в `Off` или `Initial`).
- HPA по ресурсам + VPA в режиме `Off` (для аналитики, ручное применение рекомендаций).

**Неправильно:**
- HPA по CPU + VPA с `updateMode: InPlaceOrRecreate` по CPU. Это создаст «гонку масштабирования»: VPA увеличит лимиты, HPA посчитает, что утилизация упала, и уменьшит реплики, и наоборот.

### VPA + Cluster Autoscaler / Karpenter

- VPA изменяет `requests` подов, что может привести к тому, что поды перестанут влезать на текущие узлы.
- **Cluster Autoscaler** реагирует на `Pending` поды и добавляет узлы в Node Group.
- **Karpenter** создает новые узлы подходящего размера на основе потребностей подов.
- В on-prem окружении без CA/Karpenter, VPA с `InPlaceOrRecreate` может эвиктировать под, который не влезает на текущий узел, и планировщик разместит его на другом узле с достаточной емкостью.

### VPA + Pod Disruption Budget (PDB)

- VPA Updater эвиктирует поды перед обновлением ресурсов.
- Если PDB слишком жесткий (например, `minAvailable: 100%`), VPA не сможет обновить под, и рекомендации не будут применяться.
- **Рекомендация:** `minAvailable` или `maxUnavailable` должны быть установлены с запасом (например, `maxUnavailable: 1` для приложений с 3+ репликами).

### VPA + Metrics Server

- Recommender опрашивает Metrics Server с периодом, определяемым флагом `--recommender-interval` (по умолчанию 1 минута).
- При сбоях Metrics Server рекомендации перестают обновляться.
- В on-prem окружении убедитесь, что Metrics Server имеет достаточные права на чтение метрик с всех узлов и что kubelet доступен по безопасному соединению (или настроен `--kubelet-insecure-tls` для bare metal).

### VPA + Admission Controllers

- VPA Admission Controller работает как мутирующий вебхук.
- Если в кластере есть другие мутирующие вебхуки (например, Istio, Kyverno), убедитесь, что они не конфликтуют с VPA.
- Порядок вебхуков важен: VPA должен применять ресурсы после любых вебхуков, которые могут изменять спецификацию пода.

---

## Мониторинг и алертинг

### Ключевые метрики Prometheus

VPA не экспортирует метрики по умолчанию, но их можно получить через kube-state-metrics и логи.

| Метрика | Источник | Описание |
| :--- | :--- | :--- |
| `kube_pod_status_phase` | kube-state-metrics | Отслеживание подов в `Pending` после эвикции VPA |
| `container_cpu_usage_seconds_total` | cAdvisor/Metrics Server | Фактическое потребление CPU |
| `container_memory_working_set_bytes` | cAdvisor/Metrics Server | Фактическое потребление памяти |
| `kube_event` | kube-eventer | События `UpdatedResoure` или `Infeasible` от VPA |
| `vpa_admission_controller_mutation_total` | custom metrics | Количество мутаций (если настроен экспорт) |

### Пример алертов Prometheus / Alertmanager

```yaml
groups:
  - name: vpa_alerts
    rules:
      - alert: VPARecommendationStale
        expr: time() - max_over_time(kube_event{reason="UpdatedResource"}[2h]) > 7200
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "VPA не обновляет рекомендации"
          description: "Последнее обновление рекомендации VPA было более 2 часов назад."

      - alert: VPAInfeasibleResize
        expr: kube_event{reason="Infeasible"} > 0
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "VPA не может применить рекомендацию"
          description: "VPA возвращает Infeasible для {{ $labels.involved_object_name }}."

      - alert: OOMKilledAfterVPA
        expr: increase(kube_event{reason="OOMKilled"}[1h]) > 0
        for: 0m
        labels:
          severity: critical
        annotations:
          summary: "Под завершился с OOMKilled после применения VPA"
          description: "Под {{ $labels.involved_object_name }} был убит из-за нехватки памяти."
```

### Команды для мониторинга

```bash
# Просмотр событий VPA за последний час
kubectl get events --all-namespaces --field-selector reason=UpdatedResource --sort-by='.lastTimestamp'

# Проверка статуса resize для конкретного пода
kubectl get pod my-app-0 -o jsonpath='{.status.containerStatuses[0].allocatedResources}'

# Сравнение desired vs allocated ресурсов
kubectl get pod my-app-0 -o jsonpath='{.spec.containers[0].resources}' && \
kubectl get pod my-app-0 -o jsonpath='{.status.containerStatuses[0].allocatedResources}'
```

---

## Траблшутинг и диагностика

### Типовые проблемы

1.  **VPA не обновляет поды:**
    -   Проверьте `updateMode`. Если он `Off` или `Initial`, работающие поды не изменятся.
    -   Проверьте наличие [PDB (Pod Disruption Budget)](./pod_disruption_budget.md). VPA не выселит под, если это нарушит PDB.
    -   Проверьте лимиты `resourcePolicy`. Если `target` выше `maxAllowed`, обновление не произойдет.
    -   Проверьте статус `status.resize` пода. Если `Infeasible` — на узле нет ресурсов.

2.  **Бесконечные перезапуски (Churn):**
    -   Слишком узкий диапазон между `lowerBound` и `upperBound`.
    -   Приложение потребляет ресурсы короткими, но мощными всплесками. Решение: увеличить окно наблюдения или выставить `minAllowed`.
    -   Конфликт с HPA по тем же метрикам (CPU/Memory).

3.  **Admission Controller Timeout:**
    -   Высокая нагрузка на API-сервер. Проверьте логи пода `vpa-admission-controller`.
    -   Проверьте время отклика API-сервера: `kubectl get --raw /healthz`.

4.  **Infeasible Resize (статус Infeasible):**
    -   VPA запросил увеличение `requests`, но на текущем узле нет свободного CPU/RAM.
    -   Проверьте `kubectl describe node <node-name>` на предмет доступных ресурсов.
    -   Убедитесь, что `requests` других подов на узле не занимают всю доступную емкость.

5.  **Recommender не обновляет рекомендации:**
    -   Проверьте доступность Metrics Server: `kubectl top pods`.
    -   Проверьте логи Recommender: `kubectl logs -n kube-system deployment/vpa-recommender`.
    -   Убедитесь, что поды имеют `resources.requests` (без них Recommender не может собрать данные).

6.  **Сайдкары блокируют масштабирование:**
    -   Если у сайдкара не заданы `requests`, HPA (и частично VPA) не может рассчитать утилизацию.
    -   Используйте `containerPolicies` с `mode: "Off"` для сайдкаров.

### Полезные команды

```bash
# Просмотр рекомендаций для конкретного VPA
kubectl describe vpa my-app-vpa

# Просмотр логов Recommender для анализа логики расчета
kubectl logs -n kube-system deployment/vpa-recommender

# Проверка событий мутации
kubectl get events --field-selector involvedObject.kind=VerticalPodAutoscaler

# Проверка статуса resize пода
kubectl get pod my-app-0 -o jsonpath='{.status.containerStatuses[0].allocatedResources}'

# Просмотр логов Admission Controller
kubectl logs -n kube-system deployment/vpa-admission-controller

# Проверка событий эвикции
kubectl get events --field-selector reason=Killing --sort-by='.lastTimestamp'
```

---

## Лучшие практики

1.  **VPA + HPA:** Никогда не используйте оба по CPU/Memory одновременно.
    -   **Правильно:** HPA по RPS + VPA по ресурсам.
    -   **Правильно:** HPA по ресурсам + VPA в режиме `Off` (для аналитики).
2.  **Специфика языков (Java/Go):**
    -   Для **Java** (JVM) используйте `-XX:MaxRAMPercentage` вместо фиксированного `-Xmx`, чтобы приложение видело изменения лимитов VPA.
    -   Для **Go** используйте `GOMEMLIMIT` (доступно с Go 1.19+), чтобы рантайм корректно работал с памятью в условиях динамических лимитов.
    -   Для **Node.js** передавайте флаг `--max-old-space-size`. V8 не умеет менять его динамически, но увеличение лимита спасет от `Fatal error: heap out of memory` на уровне ядра.
3.  **Мониторинг `uncappedTarget`:** Если это значение постоянно выше вашего `maxAllowed`, значит приложению требуется больше ресурсов, чем вы разрешили в политике.
4.  **Cgroup v2:** Убедитесь, что ваши узлы используют Cgroup v2 для полноценной поддержки In-Place Resize.
5.  **Pod Disruption Budget:** Всегда настраивайте PDB для StatefulSet и критических Deployment, чтобы VPA не эвиктировал все реплики одновременно.
6.  **Requests без Limits (Bursting):** Для приложений с переменной нагрузкой можно задавать `requests` на уровне среднего потребления, а `limits` — с запасом под пики. VPA поможет оптимизировать оба значения.
7.  **RBAC и изоляция:** Развертывайте VPA с минимально необходимыми правами. Используйте отдельный ServiceAccount для каждого компонента VPA.
8.  **Мультитенантность:** Для shared-кластеров разворачивайте VPA в каждом namespace отдельно или используйте ограничения `resourcePolicy` для предотвращения конфликтов между командами.

---

## Дополнительная информация

### Взаимодействие с Karpenter

Karpenter использует рекомендации VPA для точного подбора размера узлов. Если VPA оптимизирует `requests` подов, Karpenter может выбрать узел минимально достаточного размера, экономя ресурсы.

```yaml
# Karpenter NodePool с учетом рекомендаций VPA
apiVersion: karpenter.sh/v1beta1
kind: NodePool
metadata:
  name: default
spec:
  template:
    spec:
      nodeClassRef:
        group: karpenter.k8s.aws
        kind: EC2NodeClass
        name: default
      requirements:
        - key: karpenter.k8s.aws/instance-cpu
          operator: In
          values: ["2", "4", "8"]
  limits:
    cpu: 100
  disruption:
    consolidationPolicy: WhenEmpty
```

### Влияние на различные типы приложений

| Тип приложения | Влияние | Рекомендации |
| :--- | :--- | :--- |
| **Stateless API (Go/Rust)** | Минимальное | Идеально для In-Place Resize. Безопасно применять с `NotRequired`. |
| **Stateful (СУБД, Cache)** | Высокое | Критически полезно для вертикального масштабирования (Scale-Up) кэша или БД без потери кворума и разрыва пула коннектов. |
| **Legacy (Java 8)** | Блокирующее | Использовать только `resizePolicy: RestartContainer`. |
| **Batch-задачи** | Положительное | Позволяет поднять CPU Limit только на время тяжелого этапа вычислений. |

### Ограничения

- **Batch Workloads:** Плохо подходит для короткоживущих задач (Jobs/CronJobs), так как VPA не успевает собрать репрезентативные данные.
- **Зависимость от метрик:** При сбоях Metrics Server или Prometheus рекомендации перестают обновляться.
- **GPU и Extended Resources:** VPA не поддерживает автоматическое масштабирование GPU, HugePages или других расширенных ресурсов.
- **Ephemeral Storage:** VPA не управляет `ephemeral-storage`.

### Ссылки
-   [Goldilocks Documentation](../ToolsUtilities/goldilocks.md) — визуализация рекомендаций VPA.
-   [In-Place Pod Resize](./in_place_pod_resize.md) — детальный разбор технологии.
-   [Metrics Server](../MonitoringLogging/metrics-server.md) — основной источник данных для VPA.
-   **[Обзор автоскейлинга в K8s](./overview_concepts.md)** — иерархия методов масштабирования.
-   **[QoS классы и лимиты](../Scheduling/qos_limit_and_requests.md)** — влияние VPA на приоритетность подов.
-   **[Устранение неполадок HPA](../Troubleshooting/Common_Errors/hpa_troubleshooting.md)** — конфликты HPA и VPA.
-   **[Cluster Autoscaler](./cluster_autoscaler_detailed.md)** — взаимодействие с инфраструктурным масштабированием.
-   **[Karpenter: Обзор](./Karpenter/overview.md)** — альтернативный подход к инфраструктурному масштабированию.
