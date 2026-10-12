# Алертинг и мониторинг компонентов Autoscaling

**Актуально для:** Kubernetes 1.28–1.32+ / Prometheus 2.50+ / Prometheus Operator 0.70+ / kube-state-metrics 2.10+ / KEDA 2.14+ / Cluster Autoscaler 1.28+

## Определения

**Alerting (Оповещение)** — процесс генерации, дедупликации, фильтрации и маршрутизации уведомлений при выходе метрик за целевые пороги. В autoscaling алертинг выявляет насыщение ресурсов, сбои контроллеров масштабирования, застревание подов в очереди планировщика и деградацию Custom/External Metrics API.

**PrometheusRule** — Custom Resource Definition (CRD), предоставляемый Prometheus Operator. Позволяет декларативно определять группы правил алертинга (`alerting rules`) и правил предварительного вычисления (`recording rules`) на языке PromQL в манифестах Kubernetes.

**Aggregation Layer (Kubernetes API Aggregator)** — встроенный в `kube-apiserver` механизм проксирования запросов к дополнительным серверам API (`APIService`), регистрирующим группы `/apis/metrics.k8s.io`, `/apis/custom.metrics.k8s.io` и `/apis/external.metrics.k8s.io`.

**Flapping (Thrashing, Осцилляция масштабирования)** — патологическое состояние autoscaling, при котором количество реплик непрерывно колеблется вверх и вниз из-за резких скачков нагрузки, запаздывания метрик или неверно настроенных окон стабилизации (`stabilizationWindowSeconds`).

**SLI / SLO для autoscaling** — Service Level Indicators (индикаторы) и Service Level Objectives (целевые показатели надежности) инфраструктуры масштабирования: доступность API метрик, задержка реакции на всплеск нагрузки (Scale-Up Latency), доля успешных расширений пула узлов и процент подов, запланированных вовремя.

---

## Архитектура и принцип работы

### Потоки метрик и архитектура компонентов

Мониторинг масштабирования в on-premise и bare-metal инфраструктуре охватывает сквозную цепочку: от аппаратных метрик узлов и состояния очередей до aggregated API серверов и контроллеров Kubernetes.

```
┌────────────────────────────────────────────────────────────────────────┐
│                      Kubernetes Control Plane                          │
│                                                                        │
│   ┌────────────────────────┐         ┌─────────────────────────────┐   │
│   │ kube-controller-manager│         │        kube-apiserver       │   │
│   │   (HPA / VPA Engine)   │◄────────┤    (Aggregation Layer)      │   │
│   └────────────────────────┘         └──────────────┬──────────────┘   │
└─────────────────────────────────────────────────────┼──────────────────┘
                                                      │
         ┌────────────────────────────────────────────┼───────────────────────────┐
         │ /apis/metrics.k8s.io                       │ /apis/custom.metrics.k8s.io│ /apis/external.metrics.k8s.io
         ▼                                            ▼                           ▼
┌──────────────────┐                       ┌─────────────────────────┐ ┌─────────────────────────┐
│  Metrics Server  │                       │   Prometheus Adapter    │ │   KEDA Metrics Server   │
│  (kubelet/cAdv)  │                       │   (PromQL-транслятор)   │ │   (Внешние скейлеры)    │
└────────┬─────────┘                       └───────────┬─────────────┘ └───────────┬─────────────┘
         │                                             │                           │
         │                                             ▼                           │
         │                                  ┌────────────────────┐                 │
         │                                  │     Prometheus     │◄────────────────┘
         │                                  │   (TSDB / PromQL)  │
         │                                  └──────────┬─────────┘
         │                                             │ Scrape
         ▼                                             ▼
┌──────────────────┐            ┌───────────────────────────────────────────────┐
│  cAdvisor/Kubelet│            │             Источники метрик:                 │
│  (CPU / Память)  │            │ • kube-state-metrics (Состояние HPA, PDB, Pod)│
└──────────────────┘            │ • Cluster Autoscaler (Метрики пулов и нод)    │
                                │ • KEDA Operator (Ошибки и лаги скейлеров)     │
                                │ • VPA Recommender / Updater (Рекомендации)    │
                                └───────────────────────────────────────────────┘
```

### Жизненный цикл событий масштабирования и критические задержки

При оценке сбоев autoscaling учитывается кумулятивная задержка реакции системы:
1. **Интервал сбора метрик (Scrape Interval):** Prometheus опрашивает экспортеры каждые `15s–30s`.
2. **Окно усреднения PromQL:** адаптеры используют окна усреднения (`rate(...[2m])`), что добавляет инерцию.
3. **Цикл синхронизации HPA (`--horizontal-pod-autoscaler-sync-period`):** `kube-controller-manager` опрашивает API каждые `15s` (по умолчанию).
4. **Окно стабилизации HPA:** предотвращает осцилляцию (по умолчанию `scaleDown.stabilizationWindowSeconds = 300s`, `scaleUp = 0s`).
5. **Планирование и выделение узлов:** если узлы переполнены, поды переходят в `Pending (Unschedulable)`. Cluster Autoscaler (работающий через Cluster API или on-premise драйверы) инициирует добавление физического/виртуального узла. В bare-metal среде provisioning занимает от 3 до 15 минут.

### Каталог ключевых метрик по компонентам

#### 1. Workload Autoscaling (HPA) — `kube-state-metrics` v2+
- `kube_horizontalpodautoscaler_status_current_replicas` — фактическое количество запущенных реплик целевого объекта.
- `kube_horizontalpodautoscaler_status_desired_replicas` — вычисленное контроллером требуемое количество реплик.
- `kube_horizontalpodautoscaler_spec_min_replicas` — минимальный порог реплик из спецификации.
- `kube_horizontalpodautoscaler_spec_max_replicas` — максимальный лимит реплик из спецификации.
- `kube_horizontalpodautoscaler_status_condition{condition="...",status="..."}` — статус условий (`AbleToScale`, `ScalingActive`, `ScalingLimited`). Статус `true/false/unknown` передается в метке, значение метрики `1` (активно) или `0`.
- `kube_horizontalpodautoscaler_status_target_metric` — текущее зарегистрированное значение отслеживаемой метрики.

#### 2. Infrastructure Autoscaling (Cluster Autoscaler)
- `cluster_autoscaler_unschedulable_pods_count` — число подов в статусе `Pending`, которые планировщик не может разместить на текущих узлах.
- `cluster_autoscaler_failed_scale_ups_total` — счетчик неудачных попыток расширения пула узлов.
- `cluster_autoscaler_scaled_up_nodes_total` / `cluster_autoscaler_scaled_down_nodes_total` — счетчики добавленных и удаленных серверов.
- `cluster_autoscaler_unremovable_nodes_count` — узлы, которые не могут быть удалены (блокировка из-за PDB, non-replicated подов или локального хранилища).
- `cluster_autoscaler_last_activity` — Unix-timestamp последней операции масштабирования (детектор зависания процесса).

#### 3. Event-Driven Autoscaling (KEDA)
- `keda_scaler_errors_total` — количество ошибок опроса внешних систем очередей и брокеров.
- `keda_scaler_metrics_latency_bucket` — гистограмма времени опроса внешнего источника метрик.
- `keda_scaledobject_replicas` — текущее количество реплик, управляемое `ScaledObject`.
- `keda_scaledobject_max_replicas` — верхний порог реплик, сконфигурированный для `ScaledObject`.
- `keda_operator_errors_total` — системные ошибки управляющего контроллера KEDA.

#### 4. Vertical Autoscaling (VPA)
- `vpa_recommender_container_recommendations_cpu_cores` — рекомендованные ядра CPU для контейнера.
- `vpa_recommender_container_recommendations_memory_bytes` — рекомендованная память для контейнера.
- `vpa_updater_evicted_pods_total` — количество подов, принудительно перезапущенных VPA Updater для применения новых лимитов.

#### 5. Состояние кластера и планировщика
- `kube_pod_status_phase{phase="Pending"}` — поды, ожидающие планирования или старта (значение `1`).
- `kube_poddisruptionbudget_status_pod_disruptions_allowed` — разрешенное число одновременных эвикций по PDB.
- `kube_apiservice_status_condition{apiservice="...",condition="Available",status="true"}` — доступность агрегированных API метрик.

---

## Настройка и конфигурация

### Сценарий 1: PrometheusRule для HPA и Custom Metrics

Манифест содержит проверенные правила PromQL с корректным сопоставлением векторных меток через операторы `on(namespace, horizontalpodautoscaler)`:

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: autoscaling-workload-alerts
  namespace: monitoring
  labels:
    role: alert-rules
    prometheus: k8s
spec:
  groups:
    - name: autoscaling.hpa.rules
      rules:
        # 1. HPA не может управлять целевым ресурсом (RBAC, удален Deployment)
        - alert: HpaUnableToScale
          expr: |
            kube_horizontalpodautoscaler_status_condition{condition="AbleToScale",status="false"} == 1
          for: 10m
          labels:
            severity: warning
            tier: autoscaling
          annotations:
            summary: "HPA {{ $labels.namespace }}/{{ $labels.horizontalpodautoscaler }} не может масштабировать ресурс"
            description: "HPA перешел в состояние AbleToScale=false. Проверьте валидность targetRef, права RBAC и наличие Deployment/StatefulSet."

        # 2. Недоступность метрик (отказ Prometheus Adapter / Metrics Server)
        - alert: HpaMetricsUnavailable
          expr: |
            kube_horizontalpodautoscaler_status_condition{condition="ScalingActive",status="false"} == 1
          for: 5m
          labels:
            severity: critical
            tier: autoscaling
          annotations:
            summary: "HPA {{ $labels.namespace }}/{{ $labels.horizontalpodautoscaler }} потерял источник метрик"
            description: "Condition ScalingActive=false более 5 минут. HPA заблокирован и сохраняет текущее число реплик. Проверьте Custom Metrics APIService и работу адаптера."

        # 3. Достижение максимального лимита масштабирования
        - alert: HpaAtMaxReplicas
          expr: |
            (
              kube_horizontalpodautoscaler_status_current_replicas
              == on(namespace, horizontalpodautoscaler)
              kube_horizontalpodautoscaler_spec_max_replicas
            )
            and on(namespace, horizontalpodautoscaler)
            kube_horizontalpodautoscaler_status_condition{condition="ScalingLimited",status="true"} == 1
          for: 20m
          labels:
            severity: warning
            tier: autoscaling
          annotations:
            summary: "HPA {{ $labels.namespace }}/{{ $labels.horizontalpodautoscaler }} уперся в maxReplicas"
            description: "Приложение работает на пределе сконфигурированных реплик ({{ $value }}) более 20 минут. Требуется пересмотр лимитов или оптимизация потребления."

        # 4. Застревание scale-up (желаемое число больше текущего, но реплики не стартуют)
        - alert: HpaScaleUpStuck
          expr: |
            (
              kube_horizontalpodautoscaler_status_desired_replicas
              > on(namespace, horizontalpodautoscaler)
              kube_horizontalpodautoscaler_status_current_replicas
            )
            and on(namespace, horizontalpodautoscaler)
            (
              increase(kube_horizontalpodautoscaler_status_current_replicas[15m]) == 0
            )
            and on(namespace, horizontalpodautoscaler)
            kube_horizontalpodautoscaler_status_condition{condition="ScalingActive",status="true"} == 1
          for: 15m
          labels:
            severity: warning
            tier: autoscaling
          annotations:
            summary: "HPA {{ $labels.namespace }}/{{ $labels.horizontalpodautoscaler }} застрял при scale-up"
            description: "Контроллер рассчитал потребность в увеличении реплик, но количество подов не растет >15 минут. Проверьте квоты Namespace, PDB и статус узлов."

        # 5. Осцилляция реплик (Flapping)
        - alert: HpaReplicasFlapping
          expr: |
            changes(kube_horizontalpodautoscaler_status_current_replicas[15m]) > 8
          for: 5m
          labels:
            severity: warning
            tier: autoscaling
          annotations:
            summary: "HPA {{ $labels.namespace }}/{{ $labels.horizontalpodautoscaler }} находится в состоянии flapping"
            description: "Количество реплик изменилось {{ $value }} раз за 15 минут. Настройте behavior.scaleDown.stabilizationWindowSeconds или скорректируйте шаг масштабирования."
```

### Сценарий 2: PrometheusRule для Cluster Autoscaler и On-Premise инфраструктуры

Правила для узлового масштабирования в bare-metal / виртуализированных кластерах:

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: autoscaling-infrastructure-alerts
  namespace: monitoring
  labels:
    role: alert-rules
    prometheus: k8s
spec:
  groups:
    - name: autoscaling.infrastructure.rules
      rules:
        # 1. Сбой процесса масштабирования узлов
        - alert: ClusterAutoscalerFailedScaleUp
          expr: |
            increase(cluster_autoscaler_failed_scale_ups_total[10m]) > 0
          for: 5m
          labels:
            severity: critical
            tier: cluster-autoscaler
          annotations:
            summary: "Отказ операции scale-up в Cluster Autoscaler"
            description: "Зафиксированы неудачные попытки ввода новых узлов. В on-premise среде проверьте статус Cluster API / провайдера виртуализации, свободные IP-адреса в DHCP и физическую емкость серверов."

        # 2. Невозможность разместить поды (дефицит емкости)
        - alert: ClusterAutoscalerUnschedulablePods
          expr: |
            cluster_autoscaler_unschedulable_pods_count > 0
          for: 15m
          labels:
            severity: warning
            tier: cluster-autoscaler
          annotations:
            summary: "В кластере присутствуют неразмещаемые поды ({{ $value }})"
            description: "Поды находятся в очереди планировщика >15 минут, и Cluster Autoscaler не может выделить под них узлы (достигнут maxNodes, не совпадают NodeSelectors или taints)."

        # 3. Полная недоступность процесса Cluster Autoscaler
        - alert: ClusterAutoscalerDown
          expr: |
            absent(up{job="cluster-autoscaler"} == 1)
          for: 5m
          labels:
            severity: critical
            tier: cluster-autoscaler
          annotations:
            summary: "Cluster Autoscaler недоступен"
            description: "Экземпляр Cluster Autoscaler не отвечает на запросы мониторинга более 5 минут. Автоматическое масштабирование пула серверов остановлено."

        # 4. Детектор зависания Autoscaler (stuck)
        - alert: ClusterAutoscalerStuck
          expr: |
            (time() - cluster_autoscaler_last_activity > 1800)
            and
            (cluster_autoscaler_unschedulable_pods_count > 0)
          for: 5m
          labels:
            severity: critical
            tier: cluster-autoscaler
          annotations:
            summary: "Cluster Autoscaler завис при наличии очереди подов"
            description: "CA не производил полезных действий более 30 минут, несмотря на наличие {{ $value }} подов в статусе Unschedulable. Проверьте логи контроллера на дедлоки API."

        # 5. Узлы заблокированы от scale-down
        - alert: ClusterAutoscalerHighUnremovableNodes
          expr: |
            cluster_autoscaler_unremovable_nodes_count > 5
          for: 1h
          labels:
            severity: info
            tier: cluster-autoscaler
          annotations:
            summary: "Множество узлов не могут быть освобождены ({{ $value }} узлов)"
            description: "Более 5 узлов заблокированы от scale-down в течение часа. Возможные причины: жесткие PDB, поды с local-storage без emptyDir, либо поды в kube-system без PDB/tolerations."

        # 6. Застревание подов в Pending (универсальный SRE-алерт)
        - alert: PodsPendingExcessiveDuration
          expr: |
            kube_pod_status_phase{phase="Pending"} == 1
          for: 15m
          labels:
            severity: warning
            tier: workload
          annotations:
            summary: "Под {{ $labels.namespace }}/{{ $labels.pod }} застрял в Pending"
            description: "Под не может запуститься более 15 минут. Проверьте события `kubectl describe pod`, affinity/taints, PVC и наличие свободных вычислительных ресурсов."
```

### Сценарий 3: PrometheusRule для KEDA, VPA и Aggregation Layer

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: autoscaling-components-alerts
  namespace: monitoring
  labels:
    role: alert-rules
    prometheus: k8s
spec:
  groups:
    - name: autoscaling.components.rules
      rules:
        # 1. Сбои скейлеров KEDA
        - alert: KedaScalerErrorsHigh
          expr: |
            rate(keda_scaler_errors_total[5m]) > 0.05
          for: 5m
          labels:
            severity: warning
            tier: keda
          annotations:
            summary: "Высокий уровень ошибок скейлера KEDA ({{ $labels.scaler }})"
            description: "KEDA не может опросить внешний триггер (RabbitMQ, Kafka, PostgreSQL). Проверьте TriggerAuthentication, доступность сетевых портов и аутентификацию."

        # 2. Высокая задержка опроса внешнего источника KEDA
        - alert: KedaScalerMetricsLatencyHigh
          expr: |
            histogram_quantile(0.95, rate(keda_scaler_metrics_latency_bucket[5m])) > 5
          for: 10m
          labels:
            severity: warning
            tier: keda
          annotations:
            summary: "Задержка сбора метрик KEDA превышает 5 секунд"
            description: "Время опроса внешних триггеров выросло (p95 > 5s). Это вызывает задержку в реакции HPA на всплески входящих сообщений."

        # 3. KEDA ScaledObject достиг максимума
        - alert: KedaScaledObjectAtMaxReplicas
          expr: |
            keda_scaledobject_replicas >= on(namespace, scaledobject) keda_scaledobject_max_replicas
          for: 30m
          labels:
            severity: warning
            tier: keda
          annotations:
            summary: "ScaledObject {{ $labels.namespace }}/{{ $labels.scaledobject }} достиг maxReplicaCount"
            description: "Обработка очереди достигла верхнего предела масштабирования. Возможен рост лага очереди сообщений."

        # 4. Недоступность VPA Recommender
        - alert: VpaRecommenderDown
          expr: |
            absent(up{job="vpa-recommender"} == 1)
          for: 10m
          labels:
            severity: warning
            tier: vpa
          annotations:
            summary: "VPA Recommender недоступен"
            description: "Компонент VPA Recommender не генерирует метрики. Рекомендации по ресурсам контейнеров не обновляются."

        # 5. Отказ Aggregated APIService
        - alert: CustomMetricsAPIServiceUnavailable
          expr: |
            kube_apiservice_status_condition{apiservice=~"v1beta1.(custom|external).metrics.k8s.io",condition="Available",status="false"} == 1
          for: 3m
          labels:
            severity: critical
            tier: aggregation-layer
          annotations:
            summary: "APIService {{ $labels.apiservice }} находится в статусе Not Available"
            description: "kube-apiserver не может проксировать запросы к Prometheus Adapter / KEDA. HPA для всех custom/external метрик заблокирован."
```

### Сценарий 4: Recording Rules для вычисления SLI/SLO

Recording rules ускоряют дашборды Grafana и позволяют отслеживать стабильность работы autoscaling:

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: autoscaling-recording-rules
  namespace: monitoring
  labels:
    role: alert-rules
    prometheus: k8s
spec:
  groups:
    - name: autoscaling.sli.recording
      interval: 30s
      rules:
        # Доля HPA, успешно получающих метрики (HPA Availability SLI)
        - record: autoscaling:hpa_active_ratio
          expr: |
            sum(kube_horizontalpodautoscaler_status_condition{condition="ScalingActive",status="true"} == 1)
            /
            sum(kube_horizontalpodautoscaler_status_condition{condition="ScalingActive"} >= 0)

        # Доля HPA, упершихся в лимит maxReplicas (Saturation Ratio)
        - record: autoscaling:hpa_saturation_ratio
          expr: |
            sum(
              (
                kube_horizontalpodautoscaler_status_current_replicas
                == on(namespace, horizontalpodautoscaler)
                kube_horizontalpodautoscaler_spec_max_replicas
              )
              and on(namespace, horizontalpodautoscaler)
              kube_horizontalpodautoscaler_status_condition{condition="ScalingLimited",status="true"} == 1
            )
            /
            count(kube_horizontalpodautoscaler_spec_max_replicas)

        # Успешность scale-up операций Cluster Autoscaler за часовое окно
        - record: autoscaling:cluster_autoscaler_success_rate_1h
          expr: |
            rate(cluster_autoscaler_scaled_up_nodes_total[1h])
            /
            (
              rate(cluster_autoscaler_scaled_up_nodes_total[1h])
              + rate(cluster_autoscaler_failed_scale_ups_total[1h])
            )

        # Количество подов в Pending по причине нехватки ресурсов
        - record: autoscaling:unschedulable_workload_pods
          expr: |
            sum(kube_pod_status_phase{phase="Pending"} == 1)
```

### Сценарий 5: Alertmanager Inhibition Rules для предотвращения лавины алертов

При отказе `Prometheus Adapter` сотни HPA переходят в состояние `ScalingActive=false`. Чтобы дежурный инженер не получил сотни однотипных уведомлений, настраивается правило подавления (`inhibit_rules`) в [Alertmanager](../../Prometheus/alertmanager.md):

```yaml
# Фрагмент конфигурации Alertmanager (alertmanager.yaml)
inhibit_rules:
  # Если Custom Metrics APIService недоступен, подавляем алерты отдельных HPA о потере метрик
  - source_matchers:
      - alertname = "CustomMetricsAPIServiceUnavailable"
      - severity = "critical"
    target_matchers:
      - alertname = "HpaMetricsUnavailable"
    # Подавление работает глобально для всего кластера
    equal: ['prometheus']

  # Если Cluster Autoscaler упал или не может добавить узлы, подавляем ворнинги застрявших HPA
  - source_matchers:
      - alertname =~ "ClusterAutoscaler(Down|FailedScaleUp)"
      - severity = "critical"
    target_matchers:
      - alertname =~ "HpaScaleUpStuck|PodsPendingExcessiveDuration"
    equal: ['tier']
```

---

## Команды и операции

### Проверка работоспособности Aggregation Layer и адаптеров

Проверка статуса регистрации сервисов метрик в `kube-apiserver`:

```bash
kubectl get apiservice | grep -E "metrics.k8s.io"
# → v1beta1.custom.metrics.k8s.io          monitoring/prometheus-adapter   True        42d
# → v1beta1.external.metrics.k8s.io        monitoring/prometheus-adapter   True        42d
# → v1beta1.metrics.k8s.io                 kube-system/metrics-server      True        42d
```

Проверка детального состояния Custom Metrics API:

```bash
kubectl describe apiservice v1beta1.custom.metrics.k8s.io
# → Status:
# →   Conditions:
# →     Last Transition Time:  2026-09-01T10:00:00Z
# →     Message:               all checks passed
# →     Reason:                Passed
# →     Status:                True
# →     Type:                  Available
```

### Проверка отдачи сырых метрик через kubectl

Тестирование выдачи метрик напрямую через API Kubernetes минуя HPA контроллер:

```bash
kubectl get --raw "/apis/custom.metrics.k8s.io/v1beta1" | jq .resources[].name -r | head -n 5
# → pods/http_requests_per_second
# → namespaces/http_requests_per_second
# → pods/jvm_memory_used_bytes
# → services/nginx_connections_active
# → pods/grpc_server_handled_total
```

Запрос значения конкретной метрики пода:

```bash
kubectl get --raw "/apis/custom.metrics.k8s.io/v1beta1/namespaces/default/pods/*/http_requests_per_second" | jq .
# → {
# →   "kind": "MetricValueList",
# →   "apiVersion": "custom.metrics.k8s.io/v1beta1",
# →   "metadata": { "selfLink": "/apis/custom.metrics.k8s.io/v1beta1/namespaces/default/pods/*/http_requests_per_second" },
# →   "items": [
# →     {
# →       "describedObject": { "kind": "Pod", "namespace": "default", "name": "api-gateway-69f8c-8x2lq", "apiVersion": "/v1" },
# →       "metricName": "http_requests_per_second",
# →       "timestamp": "2026-10-12T17:40:00Z",
# →       "value": "250m"
# →     }
# →   ]
# → }
```

### Диагностика статуса и условий HPA в CLI

Инспекция условий масштабирования конкретного объекта:

```bash
kubectl get hpa api-gateway -n default
# → NAME          REFERENCE                TARGETS           MINPODS   MAXPODS   REPLICAS   AGE
# → api-gateway   Deployment/api-gateway   150m/500m (avg)   3         20        5          14d

kubectl get hpa api-gateway -n default -o jsonpath='{range .status.conditions[*]}{.type}{"\t"}{.status}{"\t"}{.reason}{"\n"}{end}'
# → AbleToScale      True    ReadyForNewScale
# → ScalingActive    True    ValidMetricFound
# → ScalingLimited   False   DesiredWithinRange
```

### Валидация и тестирование правил PromQL через promtool

Проверка синтаксиса манифеста `PrometheusRule`:

```bash
promtool check rules /etc/prometheus/rules/autoscaling-rules.yaml
# → Checking /etc/prometheus/rules/autoscaling-rules.yaml
# →   SUCCESS: 16 rules found
```

Проверка ответа PromQL запроса к Prometheus через `curl`:

```bash
curl -s -G http://prometheus-k8s.monitoring.svc:9090/api/v1/query \
  --data-urlencode 'query=kube_horizontalpodautoscaler_status_condition{condition="ScalingActive",status="false"} == 1' | jq .data.result
# → []
```

---

## Устранение неполадок

### Матрица типовых сбоев мониторинга и алертинга

| Симптом / Сбой | Вероятная причина | Метод диагностики | Способ устранения |
|:---|:---|:---|:---|
| Алерт `HpaMetricsUnavailable` горит для всех HPA | Упал под Prometheus Adapter или просрочился сертификат APIService | `kubectl get apiservice v1beta1.custom.metrics.k8s.io -o yaml` | Перезапустить под адаптера; проверить срок действия сертификатов в секрете `cm-adapter-serving-certs`. |
| Алерт `HpaAtMaxReplicas` не срабатывает при заполнении реплик | Ошибка сопоставления меток в PromQL (отсутствует `on(namespace, horizontalpodautoscaler)`) | Выполнить запрос в Prometheus Expression Browser | Использовать бинарное сопоставление с `on(namespace, horizontalpodautoscaler)` между метриками с разным набором меток. |
| Алерт `PodsPendingExcessiveDuration` срабатывает ложно | Неверное условие PromQL: сравнение `kube_pod_status_phase` с числом секунд вместо значения `1` | Проверить выражение алерта | Задать `kube_pod_status_phase{phase="Pending"} == 1` с параметром `for: 15m`. |
| Алерт `HpaReplicasFlapping` генерирует шум во время деплоя | Роллинг-апдейт меняет количество реплик ступенчато | `kubectl rollout status deployment/<name>` | Увеличить окно `changes(...)` до 15–20 минут или добавить фильтрацию по namespace/labels в правило. |
| Prometheus Adapter не видит кастомную метрику | Ошибка в `seriesQuery` или метрика не имеет метки `namespace` / `pod` | `kubectl logs -n monitoring -l app=prometheus-adapter` | Добавить relabeling в конфигурацию Prometheus для сохранения меток `kubernetes_pod_name` или отредактировать Discovery Rule. |
| Cluster Autoscaler рапортует `failed_scale_ups_total` в on-prem | Исчерпан пул свободных IP в DHCP; нет свободных гипервизоров/хостов | Проверить логи CA: `kubectl logs -n kube-system -l app=cluster-autoscaler` | Расширить DHCP-пул, освободить серверы в bare-metal стойке, скорректировать лимит `max-nodes-total`. |

### Диагностика разрыва векторного сопоставления в PromQL

Частая ошибка при написании правил для HPA:
```promql
# ОШИБКА: возвращает пустой вектор!
# Вектор слева содержит метку condition="ScalingLimited", а вектор справа — нет.
kube_horizontalpodautoscaler_status_condition{condition="ScalingLimited",status="true"} == 1
and
kube_horizontalpodautoscaler_status_current_replicas == kube_horizontalpodautoscaler_spec_max_replicas
```

Корректный синтаксис требует строгого указания общих меток:
```promql
# ПРАВИЛЬНО: сопоставление строго по namespace и имени HPA
(
  kube_horizontalpodautoscaler_status_current_replicas
  == on(namespace, horizontalpodautoscaler)
  kube_horizontalpodautoscaler_spec_max_replicas
)
and on(namespace, horizontalpodautoscaler)
kube_horizontalpodautoscaler_status_condition{condition="ScalingLimited",status="true"} == 1
```

---

## Рекомендации и лучшие практики

### Градация уровней критичности алертов (SRE Tiering)

1. **Critical (P1 — немедленный вызов дежурного / пейджер):**
   - Полная недоступность Custom Metrics API (`CustomMetricsAPIServiceUnavailable`).
   - Отказ контроллера Cluster Autoscaler (`ClusterAutoscalerDown`) при наличии подов в очереди.
   - Потеря источника метрик на критичных сервисах уровня tier-1 (`HpaMetricsUnavailable`).
2. **Warning (P2 — тикет или уведомление в рабочий канал в течение часа):**
   - HPA уперся в `maxReplicas` более 20 минут (`HpaAtMaxReplicas`).
   - Поды находятся в статусе `Pending` более 15 минут (`PodsPendingExcessiveDuration`).
   - Высокий уровень ошибок скейлера KEDA (`KedaScalerErrorsHigh`).
   - Осцилляция реплик (`HpaReplicasFlapping`).
3. **Info (P3 — отчет / ретроспектива раз в неделю):**
   - Узлы заблокированы от scale-down из-за PDB (`ClusterAutoscalerHighUnremovableNodes`).
   - Отклонение реального потребления от рекомендаций VPA.

### Антипаттерны мониторинга autoscaling

- **Установка параметра `for:` меньше цикла HPA:** Если период проверки HPA равен 15 секундам, установка `for: 30s` на алерт метрик приведет к ложным срабатываниям во время сетевых задержек. Минимальное рекомендуемое время — `for: 5m`.
- **Использование `$labels` для не существующих в метрике параметров:** Обращение вида `{{ $labels.kube_horizontalpodautoscaler_status_desired_replicas }}` в аннотациях аварийно завершится или выведет пустоту. Текущее значение выражения должно считываться через `{{ $value }}`.
- **Мониторинг autoscaling только по метрикам контейнеров:** Если отслеживать только загрузку CPU подов (`container_cpu_usage_seconds_total`), невозможно понять, почему не запускаются новые реплики. Мониторинг должен обязательно включать метрики `kube-state-metrics` (`status_condition`).
- **Отсутствие правил подавления (Inhibition):** При выходе из строя `kube-state-metrics` или API-сервера генерируются сотни алертов по каждому HPA. Обязательно настраивайте `inhibit_rules` в Alertmanager.

### Рекомендуемая структура дашборда Grafana

Для эффективного обзора autoscaling на дашборде создаются 4 логические строки:
1. **Строка 1: Здоровье инфраструктуры масштабирования (Overview Stat Panels)**
   - Доступность APIService (`custom.metrics.k8s.io`, `metrics.k8s.io`).
   - Общее число HPA в состоянии `ScalingActive=true` vs `ScalingActive=false`.
   - Число Unschedulable подов в кластере.
2. **Строка 2: Насыщение и лимиты HPA (Time Series & Bar Gauges)**
   - Соотношение `current_replicas` к `spec_max_replicas` (Saturation Gauge по каждому сервису).
   - График `desired_replicas` vs `current_replicas` с подсветкой дельт.
3. **Строка 3: Инфраструктурный пул узлов (Cluster Autoscaler)**
   - Динамика количества узлов в разрезе групп/пулов серверов.
   - Скорость добавления серверов (`rate(cluster_autoscaler_scaled_up_nodes_total[1h])`).
   - Заблокированные узлы (`cluster_autoscaler_unremovable_nodes_count`).
4. **Строка 4: Задержки и ошибки компонентов (Latency & Errors)**
   - p95/p99 задержки ответов Prometheus Adapter / KEDA.
   - Ошибки внешних скейлеров (`keda_scaler_errors_total`).

---

## Дополнительная информация

### Матрица SLI/SLO для систем масштабирования

| SLI (Индикатор уровня сервиса) | Формула вычисления PromQL | Целевой SLO | Действие при нарушении |
|:---|:---|:---|:---|
| **HPA Metrics Availability** | `autoscaling:hpa_active_ratio` | ≥ 99.9% за 30 дней | Проверка отказоустойчивости Prometheus Adapter (увеличение реплик, HPA для самого адаптера). |
| **Node Provisioning Latency** | Время от появления `Pending` пода до перехода узла в `Ready` | < 10 минут (on-prem) | Оптимизация сетевой загрузки PXE/OS образов, предварительный прогрев пула хостов. |
| **Scale-Up Success Rate** | `autoscaling:cluster_autoscaler_success_rate_1h` | ≥ 99.5% | Аудит аппаратной емкости дата-центра, проверка сетевых лимитов коммутаторов. |
| **Workload Scheduling Timeliness** | Доля подов, перешедших из `Pending` в `Running` за < 120s | ≥ 98% | Настройка буферных подов с низким приоритетом (`PriorityClass`) для резервирования места. |

### См. также

- [Cluster Autoscaler: Детальный обзор](cluster_autoscaler_detailed.md) — внутреннее устройство и параметры CA
- [On-Premise Autoscaling](on_premise_autoscaling.md) — особенности автомасштабирования на собственном оборудовании
- [HPA: Архитектура и концепции](HPA/hpa_concepts.md) — математика и базовые алгоритмы расчета реплик
- [HPA: Продвинутые параметры](HPA/hpa_advanced.md) — настройка правил стабилизации и демпфирования
- [HPA: Устранение неполадок](../Troubleshooting/Common_Errors/hpa_troubleshooting.md) — пошаговый траблшутинг сбоев HPA
- [Prometheus Adapter: Настройка и интеграция](HPA/prometheus_adapter_setup.md) — развертывание и конфигурация Discovery Rules
- [KEDA: Мониторинг и эксплуатация](keda/keda-operations.md) — детальный мониторинг оператора KEDA и скейлеров
- [VPA: Глубокое погружение](vpa_detailed.md) — архитектура Recommender, Updater и Admission Controller
- [Pod Disruption Budget](pod_disruption_budget.md) — защита доступности приложений при scale-down
- [Alertmanager: Маршрутизация и обработка оповещений](../../Prometheus/alertmanager.md) — конфигурация группировки, inhibition и каналов доставки
