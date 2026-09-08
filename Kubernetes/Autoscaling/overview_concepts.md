# Автоматическое масштабирование в Kubernetes: Архитектурный обзор и концепции

## Определения

**Автоматическое масштабирование (Autoscaling)** — фундаментальная возможность Kubernetes динамически изменять вычислительные ресурсы кластера и приложений в реальном времени. В современной экосистеме (Kubernetes 1.35+, состояние на 2026 год) масштабирование перешло от простой реакции на метрики к «ресурсно-ориентированному» планированию, учитывающему Dynamic Resource Allocation (DRA), жизненный цикл нативных сайдкаров и возможность изменения ресурсов без перезапуска подов.

**Горизонтальное масштабирование (Horizontal Scaling)** — изменение количества экземпляров (подов). Позволяет распределять нагрузку и обеспечивать отказоустойчивость.
*   **Scale-out (Масштабирование вовне):** Расширение системы путем добавления дополнительных экземпляров или узлов для адаптации к растущим нагрузкам.
*   **Scale-in (Масштабирование внутрь):** Сокращение количества экземпляров при снижении спроса для оптимизации использования ресурсов и затрат.

**Вертикальное масштабирование (Vertical Scaling)** — изменение ресурсов (CPU, memory), выделенных конкретному поду. Включает как традиционный перезапуск, так и современный **In-Place Pod Resize**.
*   **Scale-up (Масштабирование вверх):** Увеличение мощности существующих ресурсов (например, добавление CPU или памяти на один сервер/под). Ограничено физическими пределами одного узла.
*   **Scale-down (Масштабирование вниз):** Уменьшение выделенной мощности ресурсов в периоды низкой нагрузки для экономии эксплуатационных расходов.

## Методы масштабирования

В Kubernetes существует два принципиальных подхода к управлению мощностью системы:

### 1. Ручное масштабирование (Manual Scaling)

Пользователь напрямую подает команду на изменение количества реплик. Это полезно для разовых задач или когда автоматика не справляется.
*   **Команда `kubectl scale`**:
    ```bash
    # Увеличение количества реплик до 5 (Scale-out)
    kubectl scale deployment nginx-deployment --replicas=5
    # → deployment.apps/nginx-deployment scaled

    # Уменьшение до 0 (Scale-in / Shutdown)
    kubectl scale deployment nginx-deployment --replicas=0
    # → deployment.apps/nginx-deployment scaled
    ```

### 2. Автоматическое масштабирование (Autoscaling)

Система самостоятельно принимает решения на основе метрик (CPU, RAM, RPS) без участия человека.
*   **Горизонтальное**: [HPA](HPA/index.md) и [KEDA](./keda/keda_concepts.md).
*   **Вертикальное**: [VPA](vpa_detailed.md).
*   **Инфраструктурное**: [Cluster Autoscaler](cluster_autoscaler_detailed.md) и [Karpenter](./Karpenter/overview.md).

## Базовые концепции

### Иерархия уровней масштабирования

Масштабирование в Kubernetes работает на двух основных уровнях: уровне приложений (Workload) и уровне инфраструктуры (Infrastructure).

| Уровень | Объект | Компонент | Тип масштабирования | Ключевой механизм |
|---------|--------|-----------|----------------------|-------------------|
| **Приложение** | Поды | [HPA](HPA/index.md) | Горизонтальное | Репликация через Deployment/StatefulSet |
| **Приложение** | Поды | [KEDA](./keda/keda_concepts.md) | Горизонтальное | Scale-to-Zero, событийные триггеры |
| **Приложение** | Ресурсы | [VPA](vpa_detailed.md) | Вертикальное | Рекомендации и In-Place Resize / Recreate |
| **Инфраструктура** | Узлы | [Cluster Autoscaler](cluster_autoscaler_detailed.md) | Горизонтальное | Управление Node Groups |
| **Инфраструктура** | Узлы | [Karpenter](./Karpenter/overview.md) | Горизонтальное | Прямое создание узлов (Group-less) |
| **Инфраструктура** | Ресурсы | [In-Place Resize](in_place_pod_resize.md) | Вертикальное | Обновление cgroups без перезагрузки |

### Детальный разбор компонентов

#### Horizontal Pod Autoscaler (HPA)

HPA реализует «петлю управления» (Control Loop). Каждые 15 секунд (по умолчанию `--horizontal-pod-autoscaler-sync-period` в `kube-controller-manager`) контроллер опрашивает API метрик.

*   **Механизм расчета:** `desiredReplicas = ceil[currentReplicas * (currentMetricValue / targetMetricValue)]`.
*   **Толерантность:** По умолчанию 10% (`--horizontal-pod-autoscaler-tolerance`). Масштабирование происходит только если отклонение выходит за пределы `[0.9, 1.1]`. Это предотвращает «дребезг» при незначительных колебаниях.
*   **Поведение (behavior):** Блок `behavior` в `autoscaling/v2` позволяет асимметрично настроить скорость масштабирования:
    *   `scaleUp`: агрессивное масштабирование (без задержки или с минимальной) для защиты SLA.
    *   `scaleDown`: плавное масштабирование с `stabilizationWindowSeconds` (по умолчанию 300 сек) и ограничением скорости (`podsPerSecond`, `periodSeconds`), чтобы избежать флаттеринга.
*   **Источники метрик:** Metrics Server (resource metrics), Prometheus Adapter (custom metrics), KEDA (external metrics).
*   **Подробнее:** [HPA: Подробный разбор](HPA/index.md)

#### Vertical Pod Autoscaler (VPA)

VPA решает проблему «угадывания» правильных `requests` и `limits`.
*   **Алгоритм:** Recommender анализирует 95-й перцентиль CPU и 99-й перцентиль памяти за 8-дневное окно.
*   **Режимы:**
    *   `Off`: Только рекомендации. Идеально для профилирования.
    *   `Initial`: Применение при создании пода.
    *   `InPlaceOrRecreate` (Standard 2026): Приоритетное использование In-Place Resize.
*   **OOM Response:** VPA моментально реагирует на `OOMKilled`, поднимая лимиты памяти вне очереди.
*   **Подробнее:** [VPA: Подробный разбор](vpa_detailed.md)

#### Cluster Autoscaler (CA)

Традиционный механизм масштабирования инфраструктуры.
*   **Принцип:** Следит за подами в состоянии `Pending`. Если планировщик (Scheduler) не может разместить под из-за нехватки ресурсов, CA запрашивает изменение размера соответствующей Node Group.
*   **Удаление узлов:** CA помечает узлы как нежелательные, если их утилизация ниже порога (обычно 50%) в течение длительного времени (10+ минут).
*   **On-Premise:** В локальных дата-центрах CA требует интеграции с **Metal3** (Bare Metal Operator), **MAAS** или **Cluster API** для vSphere, так как отсутствует стандартизированный облачный API. Скорость добавления узлов зависит от времени bootstrap (PXE, cloud-init) — от 3 до 10 минут.
*   **Подробнее:** [Cluster Autoscaler: Подробный разбор](cluster_autoscaler_detailed.md)

#### Karpenter

Подробное описание архитектуры, жизненного цикла NodePool/NodeClaim, сравнение с Cluster Autoscaler и операционные сценарии приведены в **[Karpenter: Обзор и основные концепции](./Karpenter/overview.md)**. Для on-premise окружений (bare-metal, private cloud) Karpenter не предназначен — используйте Cluster Autoscaler с Cluster API или Volcano для пакетных нагрузок.

#### KEDA (Kubernetes Event-driven Autoscaling)

Оператор, позволяющий масштабировать нагрузку до нуля на основе внешних событий.
*   **Scalers:** Более 60 встроенных скалеров (Kafka, RabbitMQ, Redis, PostgreSQL, HTTP).
*   **Интеграция:** KEDA не заменяет HPA, а управляет им, динамически подставляя значения в `HPA object`.
*   **Scale-to-Zero:** При отсутствии событий в очереди KEDA удаляет все реплики Deployment, экономя ресурсы кластера.
*   **Подробнее:** [KEDA: Основные концепции](./keda/keda_concepts.md), [KEDA: Практические сценарии](./keda/practical_scenarios.md)

### Синергия и архитектурная цепочка

В современных кластерах (v1.35+) компоненты работают в тесной связке:

1.  **Нагрузка (Событие/Трафик):** RPS возрастает или очередь в Kafka растет.
2.  **Детекция:** **HPA** (по CPU/RAM) или **KEDA** (по событиям) инициирует увеличение количества реплик.
3.  **Планирование:** Scheduler пытается разместить новые поды.
    *   Если в поде есть **Native Sidecars**, их ресурсы учитываются в общем расчете.
    *   Если используется **DRA (Dynamic Resource Allocation)**, Scheduler ищет узлы с доступными аппаратными ускорителями.
4.  **Pending State:** Если ресурсов нет, поды переходят в `Pending`.
5.  **Infrastructure Scale-up:** **Cluster Autoscaler** (или Karpenter в облаке) замечает `Pending` поды и создает новые узлы, удовлетворяющие всем ограничениям (Affinity, DRA, Disk).
6.  **Optimization (VPA):** Параллельно **VPA** анализирует потребление. Если ресурсы пода завышены или занижены, он использует **In-Place Pod Resize** для корректировки лимитов запущенных контейнеров без прерывания трафика.
7.  **Scale-down & Consolidation:** Когда нагрузка спадает, HPA/KEDA уменьшают количество реплик, а CA/Karpenter консолидирует поды на меньшем числе узлов, удаляя лишние.

## Практические сценарии

### Сценарий 1: HPA для веб-микросервиса с тонкой настройкой поведения

**Задача:** Настроить масштабирование веб-сервиса по CPU с защитой от флаттеринга и соблюдением PDB.

1.  **Создайте Deployment с `requests`:**
    ```yaml
    apiVersion: apps/v1
    kind: Deployment
    metadata:
      name: webapp
    spec:
      replicas: 3
      selector:
        matchLabels:
          app: webapp
      template:
        metadata:
          labels:
            app: webapp
        spec:
          containers:
          - name: webapp
            image: nginx:1.25
            resources:
              requests:
                cpu: "100m"
                memory: "128Mi"
              limits:
                memory: "256Mi"
    ```

2.  **Создайте HPA с поведением:**
    ```yaml
    apiVersion: autoscaling/v2
    kind: HorizontalPodAutoscaler
    metadata:
      name: webapp-hpa
    spec:
      scaleTargetRef:
        apiVersion: apps/v1
        kind: Deployment
        name: webapp
      minReplicas: 3
      maxReplicas: 20
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
          - type: Pods
            value: 4
            periodSeconds: 60
        scaleDown:
          stabilizationWindowSeconds: 300
          policies:
          - type: Pods
            value: 2
            periodSeconds: 120
    ```

3.  **Настройте PDB:**
    ```yaml
    apiVersion: policy/v1
    kind: PodDisruptionBudget
    metadata:
      name: webapp-pdb
    spec:
      minAvailable: 2
      selector:
        matchLabels:
          app: webapp
    ```

4.  **Проверка:**
    ```bash
    kubectl apply -f deployment.yaml
    kubectl apply -f hpa.yaml
    kubectl apply -f pdb.yaml

    # Проверка статуса
    kubectl get hpa webapp-hpa
    # → NAME        REFERENCE               TARGETS   MINPODS   MAXPODS   REPLICAS
    # → webapp-hpa  Deployment/webapp       60%/50%   3         20        3

    # Имитация нагрузки
    kubectl run -i --tty load-generator --rm --image=busybox --restart=Never -- /bin/sh -c "while true; do wget -q -O- http://webapp; done"
    ```

### Сценарий 2: VPA + HPA по разным метрикам

**Задача:** VPA управляет ресурсами (память), HPA управляет репликами (RPS через KEDA).

1.  **Создайте VPA в режиме `Off` для аналитики:**
    ```yaml
    apiVersion: autoscaling.k8s.io/v1
    kind: VerticalPodAutoscaler
    metadata:
      name: webapp-vpa
    spec:
      targetRef:
        apiVersion: apps/v1
        kind: Deployment
        name: webapp
      updatePolicy:
        updateMode: "Off"
      resourcePolicy:
        containerPolicies:
        - containerName: webapp
          minAllowed:
            cpu: 50m
            memory: 64Mi
          maxAllowed:
            cpu: 2
            memory: 4Gi
    ```

2.  **Создайте KEDA ScaledObject для RPS:**
    ```yaml
    apiVersion: keda.sh/v1alpha1
    kind: ScaledObject
    metadata:
      name: webapp-scaler
    spec:
      scaleTargetRef:
        apiVersion: apps/v1
        kind: Deployment
        name: webapp
      minReplicaCount: 2
      maxReplicaCount: 30
      triggers:
      - type: prometheus
        metadata:
          serverAddress: http://prometheus:9090
          query: sum(rate(http_requests_total{app="webapp"}[2m]))
          threshold: "100"
    ```

3.  **Проверка:**
    ```bash
    kubectl apply -f vpa.yaml
    kubectl apply -f kedascaledobject.yaml

    # Просмотр рекомендаций VPA
    kubectl describe vpa webapp-vpa
    # → Recommendations:
    #     target: cpu: 150m, memory: 256Mi

    # Проверка событий KEDA
    kubectl describe scaledobject webapp-scaler
    ```

### Сценарий 3: Cluster Autoscaler в on-premise (Metal3)

**Задача:** Автоматическое добавление узлов в bare-metal кластер при нехватке ресурсов.

1.  **Убедитесь, что CA развернут с поддержкой Metal3:**
    ```bash
    # Проверка логов CA
    kubectl logs -n kube-system -l app=cluster-autoscaler | grep -i metal3
    # → I0901 12:00:00.000000 1 cluster_autoscaler.go:123] Using cloud provider: metal3
    ```

2.  **Создайте `ProvisioningRequest` для запроса узлов:**
    ```yaml
    apiVersion: provisioning.karpenter.sh/v1alpha1
    kind: ProvisioningRequest
    metadata:
      name: webapp-pr
    spec:
      claims:
      - resources:
          cpu: "2"
          memory: 4Gi
      constraints:
        nodeSelector:
          node-role.kubernetes.io/worker: ""
    ```

3.  **Имитируйте нехватку ресурсов:**
    ```bash
    # Создайте Deployment, который не влезет на текущие узлы
    kubectl create deployment bigapp --image=nginx --replicas=10 -- cpu=1 --memory=2Gi

    # CA увидит Pending поды и запросит новые узлы через Metal3
    kubectl get pods -w
    # → bigapp-xxx   0/1   Pending   0/30s   <none>
    # → bigapp-xxx   0/1   Pending   0/45s   <none>
    # → bigapp-xxx   1/1   Running   0/60s   <none>
    ```

### Сценарий 4: Защита критичного StatefulSet при scale-down

**Задача:** Настроить PDB и аннотации CA для базы данных, чтобы она не была удалена при снижении нагрузки.

1.  **Создайте StatefulSet с PDB:**
    ```yaml
    apiVersion: apps/v1
    kind: StatefulSet
    metadata:
      name: postgres
    spec:
      serviceName: postgres
      replicas: 3
      selector:
        matchLabels:
          app: postgres
      template:
        metadata:
          labels:
            app: postgres
        spec:
          containers:
          - name: postgres
            image: postgres:16
            resources:
              requests:
                cpu: 500m
                memory: 2Gi
              limits:
                memory: 4Gi
    ---
    apiVersion: policy/v1
    kind: PodDisruptionBudget
    metadata:
      name: postgres-pdb
    spec:
      minAvailable: 2
      selector:
        matchLabels:
          app: postgres
    ```

2.  **Запретите CA удалять узел с PostgreSQL:**
    ```bash
    # Получите узел, на котором работает PostgreSQL
    kubectl get pod postgres-0 -o wide
    # → NAME       READY   STATUS    RESTARTS   AGE   IP          NODE
    # → postgres-0 1/1     Running   0          10m   10.0.0.5   node-3

    # Добавьте аннотацию
    kubectl annotate node node-3 cluster-autoscaler.kubernetes.io/scale-down-disabled="true"
    ```

3.  **Проверка:**
    ```bash
    # Попробуйте вручную удалить узел (drain)
    kubectl drain node-3 --ignore-daemonsets --delete-emptydir-data --force

    # PDB предотвратит удаление более 1 реплики
    # → error: pods "postgres-1" is forbidden: PodDisruptionBudget ...
    ```

### Сценарий 5: Мониторинг событий масштабирования

**Задача:** Настроить алерты на неожиданное масштабирование и застрявшие поды в Pending.

1.  **Создайте Alertmanager правила:**
    ```yaml
    apiVersion: monitoring.coreos.com/v1
    kind: PrometheusRule
    metadata:
      name: autoscaling-alerts
      labels:
        release: prometheus
    spec:
      groups:
      - name: autoscaling.rules
        rules:
        - alert: HPAScaleUpFailed
          expr: increase(kube_hpa_status_current_replicas[5m]) == 0 and increase(kube_hpa_status_desired_replicas[5m]) > 0
          for: 5m
          labels:
            severity: warning
          annotations:
            summary: "HPA не может масштабировать {{ $labels.hpa }}"
            description: "Желаемое количество реплис выросло, но фактическое нет. Проверьте PDB, ресурсы узлов и лимиты Namespace."

        - alert: PodsPendingTooLong
          expr: kube_pod_status_phase{phase="Pending"} > 600
          for: 5m
          labels:
            severity: critical
          annotations:
            summary: "Поды в Pending более 10 минут"
            description: "Под {{ $labels.pod }} в namespace {{ $labels.namespace }} не может быть запланирован. Проверьте CA/Karpenter и ресурсы."

        - alert: ClusterAutoscalerNoScaleUp
          expr: increase(cluster_autoscaler_failed_scale_ups_total[10m]) > 0
          for: 5m
          labels:
            severity: critical
          annotations:
            summary: "CA не может добавить узлы"
            description: "Проверьте квоты облака, права IAM (если managed) или доступность железа (on-prem)."

        - alert: VPARecommenderNotRunning
          expr: up{job="vpa-recommender"} == 0
          for: 2m
          labels:
            severity: critical
          annotations:
            summary: "VPA Recommender недоступен"
            description: "VPA не анализирует метрики. Проверьте поды в namespace vpa-system."
    ```

2.  **Проверка:**
    ```bash
    kubectl apply -f alerts.yaml

    # Имитация проблемы
    kubectl scale deployment webapp --replicas=100
    # Ждем алерт
    ```

## Предварительные требования (Технический чек-лист)

1.  **Metrics Infrastructure:**
    *   **Metrics Server:** Обязателен для базовых метрик (CPU/Memory).
    *   **Prometheus / Thanos:** Требуется для Custom Metrics (RPS, задержки) и алертинга.
2.  **Resource Hygiene:**
    *   **Requests:** Должны быть заданы для 100% контейнеров. Без них CA и HPA не смогут корректно работать.
    *   **Limits:** Рекомендуется устанавливать для памяти, чтобы избежать разрастания побочных процессов.
3.  **Health Checks:**
    *   **Readiness Probes:** Критичны для HPA. Если проба не настроена, HPA может начать масштабирование до того, как поды реально готовы принимать трафик.
4.  **Disruption Management:**
    *   **Pod Disruption Budget (PDB):** Минимум `maxUnavailable: 1` или `minAvailable` для всех масштабируемых приложений. [Подробнее](pod_disruption_budget.md).
5.  **On-Premise specifics:**
    *   **Bare-metal:** CA требует Metal3/MAAS/Cluster API. Убедитесь, что ironic (в составе Metal3) имеет доступ к PXE и BMC (IPMI/Redfish) управлению.
    *   **Сеть:** Убедитесь, что MetalLB или другой LoadBalancer доступен для сервисов типа `LoadBalancer`, если используются.

## Лучшие практики

*   **PDB — это закон:** Всегда настраивайте [Pod Disruption Budget](pod_disruption_budget.md). VPA Updater, CA и Karpenter обязаны соблюдать PDB, что защищает вас от внезапного удаления всех реплик.
*   **Избегайте «Флаппинга» (Thrashing):** Настраивайте `stabilizationWindowSeconds` в HPA (по умолчанию 300 секунд для scale-down). Это предотвращает удаление подов сразу после кратковременного снижения нагрузки.
*   **Requests vs Реальность:** Cluster Autoscaler принимает решения на основе `requests`. Если ваши запросы сильно завышены относительно реальности, кластер будет раздуваться (Over-scaling). Используйте VPA в режиме `Off` для выравнивания `requests`.
*   **Аннотации Cluster Autoscaler:**
    *   `cluster-autoscaler.kubernetes.io/scale-down-disabled: "true"` — запрет на удаление узла с критичным подом.
    *   `cluster-autoscaler.kubernetes.io/safe-to-evict: "false"` — для подов, которые нельзя перемещать.
*   **Behavior в HPA:** Используйте расширенные политики `behavior` для контроля скорости масштабирования вверх и вниз (например, не более 10 подов в минуту при scale-down).
*   **Разделение HPA и VPA:** Никогда не настраивайте HPA и VPA на одну и ту же метрику (например, CPU). Это создаст конфликт («гонка масштабирования»). Рекомендуется: HPA по CPU/RPS, VPA в режиме `Off` или по памяти.

## Типичные ошибки и устранение неполадок

*   **HPA не масштабирует:**
    *   **Причина:** Отсутствуют `requests` в контейнере.
    *   **Диагностика:** `kubectl describe hpa <name>` — поле `Metrics` покажет `unknown` для container resource.
    *   **Решение:** Добавьте `resources.requests.cpu` в Deployment.
*   **Поды зависают в Pending:**
    *   **Причина:** CA не может добавить узлы (on-prem: нет доступного железа, cloud: достигнут лимит квоты).
    *   **Диагностика:** `kubectl get events --field-selector reason=FailedScheduling` и логи CA.
    *   **Решение:** Увеличьте `max-nodes-total`, проверьте Metal3/MAAS (on-prem) или квоты облака.
*   **VPA перезапускает поды без нужды:**
    *   **Причина:** Режим `Auto` (Recreate) вместо `InPlaceOrRecreate`.
    *   **Диагностика:** `kubectl describe vpa <name>` — поле `UpdateMode`.
    *   **Решение:** Переключитесь на `InPlaceOrRecreate` (Kubernetes 1.27+).
*   **CA удаляет узлы с критичной нагрузкой:**
    *   **Причина:** Отсутствует PDB или аннотации `safe-to-evict`.
    *   **Диагностика:** `kubectl describe node <node>` — события `ScaleDown` и `NotSafeToEvict`.
    *   **Решение:** Добавьте PDB и аннотации.
*   **KEDA не масштабирует до нуля:**
    *   **Причина:** `activationThreshold` слишком низкий, метрика не достигает нуля из-за шума.
    *   **Диагностика:** `kubectl describe scaledobject <name>` — поле `Status.Phase`.
    *   **Решение:** Настройте `activationThreshold` и проверьте логи KEDA Operator.
*   **Метрики отстают (stale metrics):**
    *   **Причина:** Metrics Server не может собрать метрики с узла (узлы под нагрузкой, cAdvisor перегружен).
    *   **Диагностика:** `kubectl top nodes` — inconsistent или `Unknown` значения.
    *   **Решение:** Увеличьте интервал скрейпинга Metrics Server, проверьте нагрузку на API-сервер.

## Дополнительная информация

### Конфликты и ограничения (Матрица совместимости)

| Конфликт | Описание и решение |
|----------|--------------------|
| **HPA + VPA (CPU)** | **Запрещено.** Решение: HPA по CPU, VPA в режиме `Off` для аналитики или VPA по памяти. |
| **ArgoCD + HPA** | Конфликт за поле `replicas`. Решение: Использование [`ignoreDifferences`](../../GitOps/ArgoCD/synchronization/ignore_differences.md) или удаление `replicas` из Git. |
| **PDB vs Scale-down** | Слишком жесткий PDB (`minAvailable: 100%`) заблокирует удаление пустых узлов. Решение: Использовать проценты или оставлять зазор. |
| **Sidecars (Pre-1.29)** | Ресурсы сайдкаров часто не учитывались корректно в HPA. В 1.35+ используйте **Native Sidecars**. |
| **CA on-prem без Cloud API** | CA не может работать без обвязки (Metal3, MAAS, Cluster API). Без нее используйте ручное или внешнее управление узлами. |

### Связанные темы и документация

*   [Pod Disruption Budget (PDB)](pod_disruption_budget.md) — защита доступности.
*   [Управление размещением подов (Affinity, TSC)](../Scheduling/affinity.md).
*   [Metrics Server и мониторинг](../MonitoringLogging/metrics-server.md).
*   [In-Place Pod Resize: Глубокое погружение](in_place_pod_resize.md).
*   [Шардирование и изоляция нагрузки](sharding.md).
